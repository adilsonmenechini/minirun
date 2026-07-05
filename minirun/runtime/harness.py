"""Runtime harness — core execution loop and bootstrap orchestration.

Orchestrates initialisation, policy enforcement, provider lifecycle, and
session finalisation.  Event-journal helpers live in :mod:`events` and
memory-context helpers in :mod:`context`.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import os
from pathlib import Path
from typing import Any

from minirun.boot import init as boot_init
from minirun.log import get_logger
from minirun.memory import (
    PROFILE_LOADED,
    TOOL_CONFIRMATION_REQUIRED,
    TOOL_DENIED,
    TOOL_REQUESTED,
)
from minirun.ports.provider import BaseProvider, Message, Response
from minirun.providers import PROVIDERS
from minirun.runtime.context import _get_default_db_path, _get_default_summary_dir
from minirun.runtime.events import init_journal, safe_emit
from minirun.security import PolicyDecision, PolicyEngine
from minirun.tools import registry
from minirun.workspace import Workspace

log = get_logger("runtime")

# Global instances initialized during bootstrap
_policy_engine: PolicyEngine | None = None
_workspace_discovery: Any | None = None


def bootstrap(allow_all: bool = False) -> None:
    """Initialize runtime: boot config, workspace, policy engine, and MCP.

    Args:
        allow_all: If True, bypass policy enforcement for all tools.
    """
    global _policy_engine
    global _workspace_discovery

    boot_init()
    ws = Workspace()
    created = ws.init()
    log.info("ws bootstrapped created=%s", created)
    _policy_engine = PolicyEngine(allow_all=allow_all)
    log.info("policy init allow_all=%s", allow_all)
    init_journal()
    log.info("tools=%d", len(registry.list_tools()))


async def bootstrap_workspace_async(
    profile_name: str | None = None, allow_all: bool = False
) -> None:
    """Async extension of bootstrap: discover workspace, activate profile MCP.

    Caller should await this AFTER bootstrap().

    Args:
        profile_name: Profile name to activate for MCP connections.
        allow_all: If True, skip policy checks for discovered tools.
    """
    global _workspace_discovery

    from minirun.workspace.discovery import WorkspaceDiscovery
    from minirun.workspace.workspace import Workspace

    ws = Workspace()
    discovery = WorkspaceDiscovery(ws.root)

    # Discover all workspace entities
    entities = discovery.discover_all()
    _workspace_discovery = discovery

    log.info(
        "discovery profiles=%d skills=%d ext=%d cmds=%d",
        len(entities["profiles"]),
        len(entities["skills"]),
        len(entities["extensions"]),
        len(entities["commands"]),
    )

    # Ensure policy engine loaded
    if _policy_engine is None:
        bootstrap(allow_all=allow_all)

    # Activate profile MCP if a profile name was given
    if profile_name:
        profile = discovery.get_profile(profile_name)
        if profile is None:
            log.warning("profile %r not found — no MCP", profile_name)
            return

        # Apply profile extensions (Phase 3)
        extensions = discovery.discover_extensions()
        if extensions:
            profile = profile.apply_extensions(extensions)
            log.info("applied %d ext(s) to %s", len(extensions), profile_name)

        from minirun.workspace.mcp_manager import MCPProfileManager

        mcp = MCPProfileManager(profile)
        try:
            await mcp.connect_all()
            log.info("mcp active %s servers=%d", profile.name, len(profile.mcp_servers))
            safe_emit(
                session_id="system",
                event_type=PROFILE_LOADED,
                payload={
                    "profile": profile_name,
                    "mcp_servers": len(profile.mcp_servers),
                },
            )
        except Exception as exc:
            log.warning("mcp activate fail %s: %s", profile.name, exc)


def get_policy_engine() -> PolicyEngine:
    """Return the global Policy Engine instance."""
    if _policy_engine is None:
        msg = "Policy Engine not initialized — call bootstrap() first"
        log.error(msg)
        raise RuntimeError(msg)
    return _policy_engine


def check_tool_permission(
    tool_name: str,
    params: dict[str, Any] | None = None,
    session_id: str | None = None,
) -> PolicyDecision:
    """Check if a tool invocation is permitted by the Policy Engine.

    Emits ``TOOL_REQUESTED`` and optionally ``TOOL_DENIED`` or
    ``TOOL_CONFIRMATION_REQUIRED`` events.

    Args:
        tool_name: Name of the tool being invoked.
        params: Parameters passed to the tool (used for path/domain checks).
        session_id: Optional session ID for event journaling.

    Returns:
        ``PolicyDecision.ALLOW``, ``.DENY``, ``.DENY_WITH_REASON``, or
        ``.REQUIRES_CONFIRMATION``.
    """
    engine = get_policy_engine()
    decision = engine.evaluate(tool_name, params)

    sid = session_id or "system"
    safe_emit(
        sid,
        TOOL_REQUESTED,
        {
            "tool": tool_name,
            "params": params,
            "decision": decision.value,
        },
    )
    if decision.needs_confirmation:
        safe_emit(
            sid,
            TOOL_CONFIRMATION_REQUIRED,
            {
                "tool": tool_name,
                "reason": decision.reason,
                "params": params,
            },
        )
    elif not decision.allowed:
        safe_emit(
            sid,
            TOOL_DENIED,
            {
                "tool": tool_name,
                "reason": decision.reason or "denied",
            },
        )
    return decision


async def finalize_session(
    session_id: str,
    prompt: str,
    messages: list[Message],
    response: Response,
    provider: BaseProvider,
    summary_dir: Path | None = None,
    db_path: Path | None = None,
) -> None:
    """Finalize a session: persist messages and generate a summary.

    Calls :func:`~minirun.memory.journal.summarize_session` with a sync
    wrapper around the async provider.  If summarisation fails a stub
    summary with error metadata is written instead.

    Args:
        session_id: UUID for the session.
        prompt: The original user prompt.
        messages: The conversation messages.
        response: The final provider response.
        provider: The LLM provider to use for summarization.
        summary_dir: Override summary directory (optional).
        db_path: Override SQLite path (optional).
    """
    from minirun.memory.journal import summarize_session

    summary_dir = summary_dir or _get_default_summary_dir()
    db_path = db_path or _get_default_db_path()

    # Build message dicts for summarize_session
    msg_dicts: list[dict[str, Any]] = []
    for m in messages:
        msg_dicts.append({"role": m.role, "content": m.content})
    if response.content:
        msg_dicts.append({"role": "assistant", "content": response.content})

    # Create a sync wrapper that bridges async provider → sync callable
    def _sync_provider(msgs: list[dict[str, Any]]) -> Any:
        p_msgs = [
            Message(role=m.get("role", "user"), content=m.get("content", ""))
            for m in msgs
        ]
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                lambda: asyncio.run(provider.complete(p_msgs, max_tokens=512))
            )
            return future.result(timeout=30)

    summarize_session(
        session_id=session_id,
        prompt=prompt,
        messages=msg_dicts,
        provider=_sync_provider,
        summary_dir=summary_dir,
        db_path=db_path,
    )


def get_provider(
    name: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    profile: str | None = None,
) -> BaseProvider:
    bootstrap()
    provider_name = name or os.environ.get("LLM_PROVIDER", "openai")
    provider_cls = PROVIDERS.get(provider_name)

    if provider_cls is None:
        available = ", ".join(sorted(PROVIDERS))
        msg = f"Unknown provider {provider_name!r}. Available: {available}"
        log.warning(msg)
        raise ValueError(msg)

    kwargs: dict[str, object] = {}
    if model is not None:
        kwargs["model"] = model
    if temperature is not None:
        kwargs["temperature"] = temperature
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens

    log.info(
        "init provider=%s model=%s temp=%s tokens=%s",
        provider_name,
        model or "default",
        temperature if temperature is not None else "default",
        max_tokens if max_tokens is not None else "default",
    )
    return provider_cls(**kwargs)
