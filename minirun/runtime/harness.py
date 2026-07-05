"""Runtime harness — core execution loop and bootstrap orchestration."""

from __future__ import annotations

import asyncio
import concurrent.futures
import os
from pathlib import Path
from typing import Any

from minirun.boot import init as boot_init
from minirun.log import get_logger
from minirun.memory.summaries import search_summaries, summarize_session
from minirun.ports.provider import BaseProvider, Message, Response
from minirun.providers import PROVIDERS
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
    log.info("Workspace bootstrapped (created=%s)", created)

    # Initialize Policy Engine
    _policy_engine = PolicyEngine(allow_all=allow_all)
    log.info("Policy Engine initialized (allow_all=%s)", allow_all)

    # Lazy-init: only run after bootstrap if explicitly requested by caller
    log.info("Tool registry has %d registered tools", len(registry.list_tools()))


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
        "Workspace discovery: %d profiles, %d skills, %d agents, %d commands",
        len(entities["profiles"]),
        len(entities["skills"]),
        len(entities["agents"]),
        len(entities["commands"]),
    )

    # Ensure policy engine loaded
    if _policy_engine is None:
        bootstrap(allow_all=allow_all)

    # Activate profile MCP if a profile name was given
    if profile_name:
        from minirun.workspace.mcp_manager import MCPProfileManager

        profile = discovery.get_profile(profile_name)
        if profile is None:
            log.warning(
                "Profile %r not found among workspace profiles; MCP not activated",
                profile_name,
            )
            return
        mcp = MCPProfileManager(profile)
        try:
            await mcp.connect_all()
            log.info(
                "MCPProfileManager activated for profile %s (%d servers configured)",
                profile.name,
                len(profile.mcp_servers),
            )
        except Exception as exc:
            log.warning(
                "MCPProfileManager failed to activate profile %s: %s",
                profile.name,
                exc,
            )


def get_policy_engine() -> PolicyEngine:
    """Return the global Policy Engine instance."""
    if _policy_engine is None:
        msg = "Policy Engine not initialized — call bootstrap() first"
        log.error(msg)
        raise RuntimeError(msg)
    return _policy_engine


def check_tool_permission(
    tool_name: str, params: dict[str, Any] | None = None
) -> PolicyDecision:
    """Check if a tool invocation is permitted by the Policy Engine.

    Args:
        tool_name: Name of the tool being invoked.
        params: Parameters passed to the tool (used for path/domain checks).

    Returns:
        PolicyDecision: ALLOW or DENY/DENY_WITH_REASON.
    """
    engine = get_policy_engine()
    return engine.evaluate(tool_name, params)


def _get_default_db_path() -> Path:
    """Return the default SQLite path for the memory index."""
    ws = Workspace()
    return ws.root / "memory" / "sessions" / "index.sqlite"


def _get_default_summary_dir() -> Path:
    """Return the default directory for session summary files."""
    ws = Workspace()
    return ws.root / "memory" / "sessions" / "summaries"


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

    Calls summarize_session() with a sync wrapper around the async provider.
    If summarization fails, a stub summary with error metadata is written
    instead (handled internally by summarize_session).

    Args:
        session_id: UUID for the session.
        prompt: The original user prompt.
        messages: The conversation messages.
        response: The final provider response.
        provider: The LLM provider to use for summarization.
        summary_dir: Override summary directory (optional).
        db_path: Override SQLite path (optional).
    """
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


def build_memory_context(
    prompt: str,
    db_path: Path | None = None,
    max_summaries: int = 2,
    knowledge_store: Any | None = None,
    profile_name: str | None = None,
    max_knowledge_facts: int = 5,
) -> str | None:
    """Build a memory context string from relevant past session summaries and knowledge.

    Queries search_summaries() for summaries matching the current prompt,
    and optionally queries KnowledgeStore for relevant facts.
    Returns None if no relevant context is found.

    Args:
        prompt: The current user prompt to match against past summaries.
        db_path: Override SQLite path (optional).
        max_summaries: Maximum number of past summaries to include.
        knowledge_store: Optional KnowledgeStore instance for fact retrieval.
        profile_name: Profile name for tag-based fact filtering.
        max_knowledge_facts: Maximum number of knowledge facts to include.

    Returns:
        Formatted context string, or None if no matches.
    """
    lines: list[str] = []
    has_context = False

    # Session summaries section
    try:
        results = search_summaries(query=prompt, limit=max_summaries, db_path=db_path)
    except Exception:
        log.warning("Failed to search past summaries", exc_info=True)
        results = []

    if results:
        has_context = True
        lines.append("The following are relevant past session summaries for context:")
        lines.append("")
        for r in results:
            created = r.get("created_at", "?")
            sid = r.get("session_id", "?")
            pr = r.get("prompt", "?")
            lines.append(f"- [{created}] Session {sid}: {pr}")
        lines.append("")

    # Knowledge facts section
    if knowledge_store is not None:
        try:
            tags = [profile_name] if profile_name else None
            facts = knowledge_store.get_relevant(
                query=prompt,
                tags=tags,
                limit=max_knowledge_facts,
            )
        except Exception:
            log.warning("Failed to query knowledge store", exc_info=True)
            facts = []

        if facts:
            has_context = True
            if results:
                lines.append("---")
                lines.append("")
            lines.append("## Relevant Knowledge")
            lines.append("")
            for f in facts:
                tags_str = ", ".join(f.tags[:3])
                preview = f.content[:80]
                lines.append(
                    f"- {preview} (tags: {tags_str}, source: {f.source_session_id[:8]})"
                )
            lines.append("")

    if not has_context:
        return None

    lines.append("Use this context to inform your response if relevant.")

    return "\n".join(lines)


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
        "Initialising provider: %s (model=%s, temperature=%s, max_tokens=%s)",
        provider_name,
        model or "default",
        temperature if temperature is not None else "default",
        max_tokens if max_tokens is not None else "default",
    )
    return provider_cls(**kwargs)
