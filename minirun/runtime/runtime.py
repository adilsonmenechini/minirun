"""Runtime — public API for executing sessions.

Wraps bootstrap, state machine, profile activation, provider calls,
memory context, and session finalisation into a single ``Runtime``
class with typed input/output contracts.

Usage::

    runtime = Runtime()
    result = await runtime.run(
        RuntimeRequest(
            profile="sre",
            message="check monitors",
        )
    )
    print(result.content)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from minirun.log import get_logger
from minirun.memory import (
    PROVIDER_CALLED,
    RESPONSE_GENERATED,
    SESSION_STARTED,
    build_knowledge,
)
from minirun.ports.provider import BaseProvider, Message
from minirun.runtime.context import build_memory_context
from minirun.runtime.events import emit_event
from minirun.runtime.harness import (
    bootstrap,
    bootstrap_workspace_async,
    finalize_session,
    get_provider,
)
from minirun.runtime.state import RuntimeState, RuntimeStateMachine
from minirun.workspace import Workspace
from minirun.workspace.discovery import WorkspaceDiscovery
from minirun.workspace.models import WorkspaceProfile

log = get_logger("runtime.api")


# ── Contracts ───────────────────────────────────────────────────────────


@dataclass
class RuntimeRequest:
    """Input contract for a single runtime execution.

    Args:
        profile: Profile name to activate (e.g. ``"sre"`` for ``@sre``).
        message: The user prompt/message.
        session_id: Optional session UUID. Auto-generated if omitted.
        provider: LLM provider name (default: ``$LLM_PROVIDER`` or ``openai``).
        model: Model identifier (default: provider default).
        temperature: Sampling temperature (default: provider default).
        max_tokens: Maximum output tokens (default: provider default).
        allow_all: Bypass policy enforcement (default: ``False``).
    """

    profile: str | None = None
    message: str = ""
    session_id: str | None = None
    provider: str | None = None
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    allow_all: bool = False


@dataclass
class RuntimeResponse:
    """Output contract from a single runtime execution.

    Args:
        content: The generated response text.
        session_id: Session UUID for this execution.
        messages: The full message list (system + user + assistant).
        provider: Provider name used.
        model: Model identifier used.
        usage: Token usage statistics.
        profile: Profile name that was activated (if any).
    """

    content: str
    session_id: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    provider: str = ""
    model: str = ""
    usage: dict[str, Any] | None = None
    profile: str | None = None


# ── Runtime ────────────────────────────────────────────────────────────


class Runtime:
    """Public API for executing sessions with minirun.

    Encapsulates the full execution lifecycle: bootstrap, profile
    activation, state machine, memory context, provider call, session
    finalisation, and knowledge extraction.

    The class is designed to be instantiated once and reused across
    multiple ``run()`` calls.
    """

    def __init__(self, allow_all: bool = False) -> None:
        """Initialise the runtime.

        Calls :func:`bootstrap` once to set up the workspace, policy
        engine, and event journal.

        Args:
            allow_all: If ``True``, bypass policy enforcement for all
                tools.  Passed to :func:`bootstrap`.
        """
        self._allow_all = allow_all
        self._bootstrapped = False
        self._provider: BaseProvider | None = None
        self._active_profile: WorkspaceProfile | None = None
        log.info("runtime init allow_all=%s", allow_all)

    # ── Lifecycle ──────────────────────────────────────────────────────

    def _ensure_bootstrapped(self) -> None:
        """Run bootstrap once, lazily."""
        if not self._bootstrapped:
            bootstrap(allow_all=self._allow_all)
            self._bootstrapped = True
            log.debug("bootstrapped")

    def _ensure_provider(
        self,
        provider_name: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> BaseProvider:
        """Return (or create) the provider instance."""
        if self._provider is None:
            self._provider = get_provider(
                name=provider_name,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        return self._provider

    @property
    def active_profile(self) -> WorkspaceProfile | None:
        """The currently active profile, if any."""
        return self._active_profile

    # ── Core execution ─────────────────────────────────────────────────

    async def run(self, request: RuntimeRequest) -> RuntimeResponse:
        """Execute a single request and return a response.

        This is the primary entry-point for the runtime.  It handles:

        1. Bootstrap (lazy, once).
        2. Profile activation and MCP server connection.
        3. Session creation and state machine initialisation.
        4. Memory context injection (past summaries, knowledge).
        5. Provider call.
        6. Session finalisation (summary generation, knowledge extraction).
        7. Response assembly.

        Args:
            request: Typed request with profile, message, and overrides.

        Returns:
            A :class:`RuntimeResponse` with the generated content and
            execution metadata.
        """
        self._ensure_bootstrapped()

        # ── 1. Profile activation ──────────────────────────────────────
        active_profile: WorkspaceProfile | None = None
        effective_message = request.message

        if request.profile:
            await bootstrap_workspace_async(
                profile_name=request.profile,
                allow_all=request.allow_all or self._allow_all,
            )
            ws = Workspace()
            discovery = WorkspaceDiscovery(ws.root)
            active_profile = discovery.get_profile(request.profile)
            if active_profile:
                self._active_profile = active_profile
                log.info(
                    "active profile=%s servers=%d",
                    active_profile.name,
                    len(active_profile.mcp_servers),
                )

        # ── 2. Provider ────────────────────────────────────────────────
        provider = self._ensure_provider(
            provider_name=request.provider,
            model=request.model,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        )

        # ── 3. Session ─────────────────────────────────────────────────
        session_id = request.session_id or str(uuid.uuid4())
        log.info("sess start %s", session_id)
        emit_event(
            session_id,
            SESSION_STARTED,
            {
                "provider": request.provider or "default",
                "model": request.model or "default",
            },
        )

        # State machine
        sm = RuntimeStateMachine(session_id)
        sm.transition(RuntimeState.BUILD_CONTEXT)

        # ── 4. Memory context ──────────────────────────────────────────
        memory_ctx = build_memory_context(
            prompt=effective_message,
            profile_name=request.profile,
        )
        messages: list[Message] = []
        if memory_ctx:
            log.info("mem ctx found")
            messages.append(Message(role="system", content=memory_ctx))

        # Inject profile system prompt
        if active_profile and active_profile.system_prompt:
            _inject_system_prompt(active_profile, messages)

        # User message
        messages.append(Message(role="user", content=effective_message))

        # ── 5. Provider call ──────────────────────────────────────────
        sm.transition(RuntimeState.CALL_PROVIDER)
        emit_event(
            session_id,
            PROVIDER_CALLED,
            {
                "num_messages": len(messages),
                "provider": request.provider or "default",
                "model": request.model or "default",
            },
        )

        response = await provider.complete(messages)
        emit_event(
            session_id,
            RESPONSE_GENERATED,
            {
                "content_length": len(response.content or ""),
                "finish_reason": getattr(response, "finish_reason", None),
            },
        )

        # ── 6. Finalisation ────────────────────────────────────────────
        sm.transition(RuntimeState.UPDATE_CONTEXT)
        sm.transition(RuntimeState.FINALIZE)

        # Persist session and generate summary
        await finalize_session(
            session_id=session_id,
            prompt=effective_message,
            messages=messages,
            response=response,
            provider=provider,
        )

        # Knowledge extraction
        msg_dicts = _messages_to_dicts(messages)
        msg_dicts.append({"role": "assistant", "content": response.content or ""})
        build_knowledge(
            messages=msg_dicts,
            source_session_id=session_id,
        )

        # ── 7. Response assembly ──────────────────────────────────────
        usage: dict[str, Any] | None = None
        if response.usage is not None:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        log.info("sess done %s", session_id)
        return RuntimeResponse(
            content=response.content or "",
            session_id=session_id,
            messages=msg_dicts,
            provider=request.provider or "default",
            model=request.model or "default",
            usage=usage,
            profile=request.profile,
        )

    # ── Chat (interactive) ──────────────────────────────────────────────




# ── Internal helpers ──────────────────────────────────────────────────


def _inject_system_prompt(
    profile: WorkspaceProfile,
    messages: list[Message],
) -> None:
    """Inject a profile's system prompt into the messages list.

    Prepends to existing system message if found; otherwise inserts
    at position 0.
    """
    if not profile.system_prompt:
        return
    for i, msg in enumerate(messages):
        if msg.role == "system":
            messages[i] = Message(
                role="system",
                content=f"{profile.system_prompt}\n\n{msg.content}",
            )
            return
    messages.insert(0, Message(role="system", content=profile.system_prompt))


def _messages_to_dicts(messages: list[Message]) -> list[dict[str, Any]]:
    """Convert Message objects to serializable dicts."""
    return [{"role": m.role, "content": m.content} for m in messages]
