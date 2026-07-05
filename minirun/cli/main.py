from __future__ import annotations

import argparse
import asyncio
import re
import readline  # noqa: F401 — line-editing for input()
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

from minirun.boot import init as boot_init
from minirun.cli.knowledge_commands import dispatch_knowledge_command
from minirun.cli.styles import (
    blue,
    build_prompt,
    cyan,
    dim,
    error,
    gray,
    green,
    header,
    magenta,
    pad,
    red,
    yellow,
)
from minirun.log import get_logger
from minirun.memory import (
    PROVIDER_CALLED,
    RESPONSE_GENERATED,
    SESSION_STARTED,
    SUMMARY_GENERATED,
    ExtractionResult,
    KnowledgeExtractor,
    KnowledgeStore,
    build_knowledge,
)
from minirun.ports.provider import Message, Response
from minirun.runtime.context import build_memory_context
from minirun.runtime.events import emit_event, get_journal
from minirun.runtime.harness import (
    bootstrap,
    bootstrap_workspace_async,
    finalize_session,
    get_provider,
)
from minirun.runtime.state import RuntimeState, RuntimeStateMachine
from minirun.tools import registry
from minirun.workspace import Workspace
from minirun.workspace.discovery import WorkspaceDiscovery
from minirun.workspace.models import WorkspaceProfile

log = get_logger("cli")

HELP_TEXT = """
Commands:
  /exit,/quit          Exit
  /session             Show session ID
  /help                This help
  /clear               Clear screen
  @<profile>           Use profile (e.g. @sre hi)
  !<cmd>               Shell command (e.g. !ls)
  /tools               Registered tools
  /profiles            Profiles
  /commands            Custom commands
  /skills              Skills
  /sessions            Journal sessions
  /events,/journal [N] Last N events (default: 20)
  /events --session <id>  Events by session
  /events --type <t>      Events by type
  /metrics             Tool metrics
  /replay <id>         Replay session
  /knowledge list      Facts
  /knowledge search <q> Search facts
  /knowledge delete <id> Delete fact
  /knowledge prune     Remove expired
"""


def _color_event_type(etype: str) -> str:
    """Color an event type string by category."""
    if etype in ("session_started", "profile_loaded"):
        return cyan(etype)
    if etype in ("provider_called", "response_generated"):
        return blue(etype)
    if etype in ("tool_executed",):
        return green(etype)
    if etype in ("tool_denied",):
        return red(etype)
    if etype in ("tool_confirmation_required",):
        return yellow(etype)
    if etype in ("state_transition",):
        return magenta(etype)
    if etype in ("summary_generated",):
        return etype
    return dim(etype)


def _list_tools() -> None:
    """Print all registered tools."""
    tools = registry.list_tools()
    if not tools:
        print("No tools registered.")
        return
    print(header(f"Registered tools ({len(tools)}):"))
    for t in tools:
        desc = t.get("description", "")
        source = t.get("_source", "builtin")
        print(f"  {pad(cyan(t['name']), 30)}  {dim(desc)}")
        if source and source != "builtin":
            src_label = gray(f"[{source}]")
            print(f"  {pad('', 30)}  {src_label}")


def _parse_profile_reference(text: str) -> tuple[str | None, str]:
    """Extract an ``@profile_name`` reference from the beginning of a message.

    Returns a tuple of ``(profile_name, clean_message)``.
    If no ``@profile`` is found, returns ``(None, text)``.

    Examples:
        ``_parse_profile_reference("@sre hi")`` → ``("sre", "hi")``
        ``_parse_profile_reference("hello")`` → ``(None, "hello")``
        ``_parse_profile_reference("@sre")`` → ``("sre", "")``
    """
    text = text.strip()
    match = re.match(r"^@(\w[\w.-]*)(?:\s+(.*))?$", text, re.DOTALL)
    if match:
        profile_name = match.group(1)
        clean_message = (match.group(2) or "").strip()
        return profile_name, clean_message
    return None, text


def _activate_profile(
    profile: WorkspaceProfile,
    messages: list[Message],
) -> None:
    """Inject a profile's ``system_prompt`` into the messages list.

    The profile's system prompt is inserted as a ``system`` message before
    any existing messages. If a ``system`` message already exists, the
    profile's prompt is prepended to it (separated by a blank line).

    Args:
        profile: The loaded workspace profile.
        messages: The message list to modify in-place.
    """
    if not profile.system_prompt:
        log.debug(
            "Profile '%s' has no system_prompt — skipping injection",
            profile.name,
        )
        return

    # Check if a system message already exists
    for i, msg in enumerate(messages):
        if msg.role == "system":
            # Prepend profile prompt to existing system message
            messages[i] = Message(
                role="system",
                content=f"{profile.system_prompt}\n\n{msg.content}",
            )
            log.debug(
                "Prepended profile '%s' system_prompt to existing system message",
                profile.name,
            )
            return

    # No existing system message — inject at position 0
    messages.insert(0, Message(role="system", content=profile.system_prompt))
    log.debug("Injected profile '%s' system_prompt as system message", profile.name)


def _list_profiles() -> None:
    """Print available profiles from workspace."""
    ws = Workspace()
    profiles = ws.discover_profiles()
    if not profiles:
        print("No profiles found in workspace/profiles/.")
        return
    print(header(f"Available profiles ({len(profiles)}):"))
    for p in profiles:
        desc = p.get("description", "")
        nm = magenta(f"@{p['name']}")
        fmt = gray(f"({p['format']})")
        ppath = gray(p['path'])
        print(f"  {pad(nm, 30)}  {dim(desc)}  {fmt} {ppath}")


def _list_skills() -> None:
    """Print installed skills from workspace."""
    ws = Workspace()
    skills = ws.discover_skills()
    if not skills:
        print("No skills found in workspace/skills/.")
        return
    print(header(f"Installed skills ({len(skills)}):"))
    for s in skills:
        desc = s.get("description", "")
        fmt = gray(f"({s['format']})")
        ppath = gray(s['path'])
        print(f"  {pad(cyan(s['name']), 30)}  {dim(desc)}  {fmt} {ppath}")


def _list_commands() -> None:
    """Print custom commands from workspace."""
    ws = Workspace()
    commands = ws.discover_commands()
    if not commands:
        print("No commands found in workspace/commands/.")
        return
    print(header(f"Custom commands ({len(commands)}):"))
    for c in commands:
        desc = c.get("description", "")
        fmt = gray(f"({c['format']})")
        ppath = gray(c['path'])
        print(f"  {pad(yellow(c['name']), 30)}  {dim(desc)}  {fmt} {ppath}")


def _list_events(raw_cmd: str) -> None:
    """Print recent events from the journal.

    Supports:
      /events                  — last 20 events
      /events 10               — last 10 events
      /events --session <id>   — events for a specific session
      /events --type <type>    — events of a specific type
    """
    try:
        journal = get_journal()
    except RuntimeError as exc:
        print(f"Journal not available: {exc}")
        return

    # Parse arguments after "/events"
    parts = raw_cmd[len("/events") :].strip().split()
    limit = 20
    session_filter: str | None = None
    type_filter: str | None = None

    i = 0
    while i < len(parts):
        part = parts[i]
        if part == "--session" and i + 1 < len(parts):
            session_filter = parts[i + 1]
            i += 2
        elif part == "--type" and i + 1 < len(parts):
            type_filter = parts[i + 1]
            i += 2
        elif part.isdigit():
            limit = int(part)
            i += 1
        else:
            i += 1

    try:
        if session_filter:
            events = journal.get_session_events(session_filter, limit=limit)
        elif type_filter:
            events = journal.get_events_by_type(type_filter, limit=limit)
        else:
            events = journal.get_recent_events(limit=limit)
    except Exception as exc:
        print(f"Error querying journal: {exc}")
        return

    if not events:
        print("No events found.")
        return

    filter_parts: list[str] = []
    if session_filter:
        filter_parts.append(f"session={session_filter[:8]}")
    if type_filter:
        filter_parts.append(f"type={type_filter}")
    filter_desc = f" ({', '.join(filter_parts)})" if filter_parts else ""

    print(f"\n{cyan('Events')}{filter_desc} ({len(events)}):")
    print(dim("─" * 100))
    for ev in events:
        ts = (ev.get("timestamp", "?") or "")[:19]
        etype = ev.get("event_type", "?")
        sid = (ev.get("session_id", "?") or "?")[:8]
        eid = (ev.get("id", "?") or "?")[:8]
        payload = ev.get("payload", {}) or {}
        preview = ""
        if isinstance(payload, dict) and payload:
            keys = [
                "tool",
                "provider",
                "profile",
                "content_length",
                "num_messages",
                "decision",
                "reason",
                "prompt",
            ]
            parts: list[str] = []
            for k in keys:
                v = payload.get(k)
                if v is not None:
                    parts.append(f"{k}={str(v)[:40]}")
            if parts:
                preview = " | " + ", ".join(parts)
        etype_colored = _color_event_type(etype)
        print(f"  {gray(ts)}  {pad(etype_colored, 20)}  {gray(sid)}  [{dim(eid)}]{preview}")  # noqa: E501
    print()


def _list_metrics() -> None:
    """Print aggregated tool execution metrics from the journal."""
    from minirun.metrics import MetricsCollector, format_metrics_summary

    try:
        journal = get_journal()
    except RuntimeError as exc:
        print(f"Journal not available: {exc}")
        return

    collector = MetricsCollector(journal)
    summary = collector.summary()

    if summary.total_events == 0:
        print("No journal events found. Run a session first to generate metrics.")
        return

    print()
    print(format_metrics_summary(summary))
    print()


def _list_sessions() -> bool:
    """List all sessions in the journal with event counts and timestamps."""
    try:
        journal = get_journal()
    except RuntimeError as exc:
        print(f"Journal not available: {exc}")
        return True

    try:
        sessions = journal.get_sessions()
    except Exception as exc:
        print(f"Error listing sessions: {exc}")
        return True

    if not sessions:
        print("No sessions found in the journal.")
        return True

    total = len(sessions)
    total_events = sum(s["event_count"] for s in sessions)

    print()
    print(cyan(f"Sessions ({total}, {total_events} events):"))
    print(dim("─" * 80))
    h_id = pad(header("ID"), 12)
    h_evt = pad(header("Evt"), 4)
    h_first = pad(header("First"), 22)
    h_last = pad(header("Last"), 22)
    print(f"  {h_id}  {h_evt}  {h_first}  {h_last}")
    print(dim("─" * 46))

    for s in sessions:
        sid = (s.get("session_id") or "?")[:8]
        count = s.get("event_count", 0)
        first = (s.get("first_event") or "")[:19]
        last = (s.get("last_event") or "")[:19]
        print(f"  {pad(gray(sid), 10)}  {count:4d}  {first:22s}  {last:22s}")

    print()
    print(dim("Use /replay <id> to see the full timeline."))
    print()
    return True


def _replay_session(raw_cmd: str) -> bool:
    """Reconstruct and display a session timeline from journal events.

    Usage: /replay <session-id>

    Args:
        raw_cmd: The full chat command string.

    Returns:
        True if the command was handled, False if not.
    """
    parts = raw_cmd.strip().split(maxsplit=1)
    if len(parts) < 2:
        print("Usage: /replay <session-id>")
        print("  Reconstruct a session from journal events (no provider call).")
        print("  Tip: use /events --session <id> to list events for a session")
        print("       before replaying it.")
        return True

    session_id = parts[1].strip()

    try:
        journal = get_journal()
    except RuntimeError as exc:
        print(f"Journal not available: {exc}")
        print("Run a session first to generate journal events.")
        return True

    from minirun.metrics.replay import SessionReplay

    replay = SessionReplay(journal)
    try:
        session = replay.reconstruct(session_id)
    except ValueError as exc:
        print(f"{exc}")
        return True
    except Exception as exc:
        print(f"Error replaying session: {exc}")
        return True

    print()
    print(replay.format_timeline(session, show_details=True))
    return True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="minirun",
        description="Deterministic runtime for executing specialised tasks with LLMs",
    )
    parser.add_argument(
        "--provider",
        choices=["openai", "anthropic"],
        default=None,
        help="LLM provider (default: $LLM_PROVIDER or openai)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Model identifier (default: env or provider default)",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=None,
        help="Sampling temperature (default: provider default)",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=None,
        help="Maximum output tokens (default: env or provider default)",
    )
    parser.add_argument(
        "--allow-all",
        action="store_true",
        default=False,
        help="Bypass policy enforcement for all tools (default: deny)",
    )
    parser.add_argument(
        "--tools",
        action="store_true",
        default=False,
        help="List registered tools and exit",
    )
    parser.add_argument(
        "--profiles",
        action="store_true",
        default=False,
        help="List available profiles and exit",
    )
    parser.add_argument(
        "--skills",
        action="store_true",
        default=False,
        help="List installed skills and exit",
    )
    parser.add_argument(
        "--commands",
        action="store_true",
        default=False,
        help="List custom commands and exit",
    )
    parser.add_argument(
        "--chat",
        action="store_true",
        default=False,
        help="Start interactive chat session",
    )
    parser.add_argument(
        "--session-id",
        type=str,
        default=None,
        help="Resume an existing session by ID",
    )
    parser.add_argument(
        "message",
        nargs="*",
        help="Prompt message to send to the LLM",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase verbosity (use -v for INFO, -vv for DEBUG)",
    )
    return parser


def dispatch_listing(args: argparse.Namespace) -> bool:
    """Dispatch listing commands. Returns True if a listing was executed."""
    if args.tools:
        _list_tools()
        return True
    if args.profiles:
        _list_profiles()
        return True
    if args.skills:
        _list_skills()
        return True
    if args.commands:
        _list_commands()
        return True
    return False


async def run(
    provider_name: str | None,
    model: str | None,
    temperature: float | None,
    max_tokens: int | None,
    message: str,
    verbose: int = 0,
    allow_all: bool = False,
) -> None:
    log_level = None
    if verbose >= 2:
        log_level = 10  # DEBUG
    elif verbose == 1:
        log_level = 20  # INFO
    boot_init(log_level=log_level)

    # Bootstrap runtime with policy engine
    bootstrap(allow_all=allow_all)

    if not message:
        print("No message provided. Use: minirun <prompt>", file=sys.stderr)
        sys.exit(1)

    # Parse @profile_name from the message
    profile_name, clean_message = _parse_profile_reference(message)
    log.debug(
        "Parsed profile reference: profile=%s, message=%s",
        profile_name,
        clean_message[:80],
    )

    # Activate profile MCP servers if specified
    active_profile: WorkspaceProfile | None = None
    if profile_name:
        await bootstrap_workspace_async(profile_name=profile_name, allow_all=allow_all)
        # Load profile to inject its system prompt
        ws = Workspace()
        discovery = WorkspaceDiscovery(ws.root)
        active_profile = discovery.get_profile(profile_name)
        if active_profile:
            log.info(
                "Activated profile '%s' with %d MCP server(s) and %d allowed tool(s)",
                active_profile.name,
                len(active_profile.mcp_servers),
                len(active_profile.allowed_tools),
            )
        else:
            log.warning(
                "Profile '%s' not found after activation — continuing without profile",
                profile_name,
            )

    # Use cleaned message (without @profile prefix)
    effective_message = clean_message if clean_message else message

    provider = get_provider(
        name=provider_name,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    # Generate session ID for persistence
    session_id = str(uuid.uuid4())
    log.info("Starting session %s", session_id)
    emit_event(
        session_id,
        SESSION_STARTED,
        {
            "provider": provider_name or "default",
            "model": model or "default",
        },
    )

    # ── Explicit state machine ───────────────────────────────────────
    sm = RuntimeStateMachine(session_id)
    log.debug("Runtime state machine initialized: %s", sm)

    # BUILD_CONTEXT
    sm.transition(RuntimeState.BUILD_CONTEXT)

    # Initialize knowledge store for context injection
    knowledge_store = KnowledgeStore()

    # Build memory context from past session summaries and knowledge
    memory_ctx = build_memory_context(
        prompt=effective_message,
        knowledge_store=knowledge_store,
    )
    messages: list[Message] = []
    if memory_ctx:
        log.info("Found relevant past context for prompt")
        messages.append(Message(role="system", content=memory_ctx))

    # Inject profile system prompt BEFORE the user message
    if active_profile:
        _activate_profile(active_profile, messages)

    messages.append(Message(role="user", content=effective_message))

    # CALL_PROVIDER
    sm.transition(RuntimeState.CALL_PROVIDER)

    emit_event(
        session_id,
        PROVIDER_CALLED,
        {
            "num_messages": len(messages),
            "provider": provider_name or "default",
            "model": model or "default",
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
    sys.stdout.write(response.content)
    if response.content and not response.content.endswith("\n"):
        sys.stdout.write("\n")

    # UPDATE_CONTEXT → FINALIZE
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

    # Post-session knowledge extraction from the response
    all_msgs = _messages_to_dicts(messages)
    all_msgs.append({"role": "assistant", "content": response.content or ""})
    build_knowledge(
        messages=all_msgs,
        source_session_id=session_id,
    )
    log.info("Session %s finalized", session_id)


async def run_chat(
    provider_name: str | None,
    model: str | None,
    temperature: float | None,
    max_tokens: int | None,
    session_id: str | None,
    verbose: int = 0,
    allow_all: bool = False,
) -> None:
    """Run an interactive chat session with REPL loop."""
    log_level = None
    if verbose >= 2:
        log_level = 10  # DEBUG
    elif verbose == 1:
        log_level = 20  # INFO
    boot_init(log_level=log_level)
    bootstrap(allow_all=allow_all)

    provider = get_provider(
        name=provider_name,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    ws = Workspace()

    # Resume or create session
    session_id = session_id or str(uuid.uuid4())
    messages: list[Message] = []
    resumed = False

    # Load past session messages if resuming
    saved_messages, _state = ws.load_session(session_id)
    if saved_messages:
        resumed = True
        for m in saved_messages:
            messages.append(
                Message(role=m.get("role", "user"), content=m.get("content", ""))
            )
        log.info("Resumed session %s (%d messages)", session_id, len(messages))

    # Emit session_started event
    emit_event(
        session_id,
        SESSION_STARTED,
        {
            "provider": provider_name or "default",
            "model": model or "default",
            "resumed": False,
        },
    )

    # ── Explicit state machine ───────────────────────────────────────
    sm = RuntimeStateMachine(session_id)
    log.debug("Runtime state machine initialized: %s", sm)

    # BUILD_CONTEXT
    sm.transition(RuntimeState.BUILD_CONTEXT)

    # Track the last provider response for finalization
    last_response: Response | None = None

    # Initialize knowledge store and extractor
    knowledge_store = KnowledgeStore()
    knowledge_extractor = KnowledgeExtractor()

    # Inject memory context from past sessions
    memory_ctx = build_memory_context(
        prompt="continue conversation",
        knowledge_store=knowledge_store,
    )
    if memory_ctx:
        messages.insert(0, Message(role="system", content=memory_ctx))
        log.debug("Injected memory context from past summaries")

    # Track active profile for context-aware prompt
    active_chat_profile: str | None = None
    _history_file = Path.home() / ".minirun_history"
    _history_max = 1000
    try:
        readline.read_history_file(str(_history_file))
        readline.set_history_length(_history_max)
    except FileNotFoundError:
        pass
    print(cyan("━━━ MiniRUN Chat ━━━"))
    print(gray(f"session {session_id[:8]}  /help for cmds"))
    if resumed:
        print(gray(f"resumed {len(messages)} msgs"))

    try:
        while True:
            try:
                user_prompt = build_prompt(active_chat_profile, session_id)
                user_input = input(f"\n{user_prompt}").strip()
            except EOFError:
                print()
                break

            if not user_input:
                continue

            # Handle chat commands
            if user_input.startswith("/"):
                cmd = user_input.lower()
                if cmd in ("/exit", "/quit"):
                    print("Exiting chat.")
                    break
                elif cmd == "/help":
                    print(HELP_TEXT.strip())
                    continue
                elif cmd == "/session":
                    print(f"Session ID: {session_id}")
                    continue
                elif dispatch_knowledge_command(cmd, knowledge_store):
                    continue
                elif cmd == "/tools":
                    _list_tools()
                    continue
                elif cmd == "/profiles":
                    _list_profiles()
                    continue
                elif cmd == "/commands":
                    _list_commands()
                    continue
                elif cmd == "/skills":
                    _list_skills()
                    continue
                elif cmd == "/sessions":
                    _list_sessions()
                    continue
                elif cmd == "/clear":
                    subprocess.call(
                        "clear" if sys.platform != "win32" else "cls", shell=True
                    )
                    continue
                elif cmd.startswith("/events") or cmd.startswith("/journal"):
                    # Normalize /journal → /events for _list_events parsing
                    normalized = cmd.replace("/journal", "/events", 1)
                    _list_events(normalized)
                    continue
                elif cmd in ("/metrics", "/stats"):
                    _list_metrics()
                    continue
                elif cmd.startswith("/replay"):
                    _replay_session(user_input)
                    continue
                else:
                    print(f"Unknown: {user_input}. /help for cmds.")
                    continue

            # Parse @profile_name from chat input
            profile_name, clean_input = _parse_profile_reference(user_input)
            if profile_name:
                log.info("Chat profile switch: %s", profile_name)
                await bootstrap_workspace_async(
                    profile_name=profile_name, allow_all=allow_all
                )
                ws_discovery = WorkspaceDiscovery(ws.root)
                chat_profile = ws_discovery.get_profile(profile_name)
                if chat_profile:
                    _activate_profile(chat_profile, messages)
                    log.info("Injected profile '%s' prompt", profile_name)
                active_chat_profile = profile_name
                user_input = clean_input or ""
                if not user_input:
                    print(green(f"✓ Activated @{profile_name}"))
                    continue

            # Execute shell commands (! prefix)
            if user_input.startswith("!"):
                shell_cmd = user_input[1:].strip()
                if not shell_cmd:
                    print("Usage: !<command>  (e.g. !ls -lha)")
                    continue
                print(f"$ {shell_cmd}")
                try:
                    rc = subprocess.call(shell_cmd, shell=True)
                    if rc != 0:
                        print(f"[Exit code: {rc}]")
                except Exception as exc:
                    print(f"Error executing command: {exc}")
                continue

            # Send message to provider
            messages.append(Message(role="user", content=user_input))

            # CALL_PROVIDER
            sm.transition(RuntimeState.CALL_PROVIDER)

            emit_event(
                session_id,
                PROVIDER_CALLED,
                {
                    "num_messages": len(messages),
                    "provider": provider_name or "default",
                    "model": model or "default",
                },
            )
            # Print response label before streaming
            resp_label = active_chat_profile or "minirun"
            resp_color = magenta if active_chat_profile else cyan
            sys.stdout.write(f"\n{resp_color(resp_label)}: ")
            sys.stdout.flush()

            try:
                provider_response = await provider.stream_complete(messages)
            except Exception as exc:
                log.error("Provider call failed: %s", exc)
                print(f"\n{error(f'Error: {exc}')}")
                messages.pop()
                continue

            output = provider_response.content or ""
            emit_event(
                session_id,
                RESPONSE_GENERATED,
                {"content_length": len(output)},
            )
            if output and not output.endswith("\n"):
                sys.stdout.write("\n")

            messages.append(Message(role="assistant", content=output))

            # UPDATE_CONTEXT
            sm.transition(RuntimeState.UPDATE_CONTEXT)

            # Extract knowledge facts from the response
            try:
                result: ExtractionResult = knowledge_extractor.extract(
                    content=output,
                    source_session_id=session_id,
                    tags=None,
                )
                for fact in result.facts:
                    knowledge_store.upsert(fact)
                if result.facts:
                    log.debug(
                        "Extracted %d knowledge fact(s) (%d skipped)",
                        len(result.facts),
                        result.skipped_count,
                    )
            except Exception as exc:
                log.warning("Knowledge extraction failed: %s", exc)
            last_response = provider_response

            # Persist periodically (every 2 rounds)
            user_msg_count = sum(1 for m in messages if m.role == "user")
            if user_msg_count % 2 == 0:
                ws.save_session(session_id, _messages_to_dicts(messages), {})

    except KeyboardInterrupt:
        print("\n\nInterrupted.")

    # FINALIZE
    sm.transition(RuntimeState.FINALIZE)

    # Finalize: persist and generate summary
    print("\nFinalizing session...")
    ws.save_session(session_id, _messages_to_dicts(messages), {})

    # Build a summary prompt from the conversation
    first_prompt = ""
    for m in messages:
        if m.role == "user":
            first_prompt = m.content
            break

    if first_prompt:
        # Use the last provider response for summarization, or a dummy
        summary_response = (
            last_response if last_response is not None else Response(content="")
        )
        try:
            await finalize_session(
                session_id=session_id,
                prompt=first_prompt,
                messages=messages,
                response=summary_response,
                provider=provider,
            )
            emit_event(
                session_id,
                SUMMARY_GENERATED,
                {
                    "prompt": first_prompt[:80],
                },
            )
        except Exception as exc:
            log.warning("Failed to finalize session: %s", exc)

    # Post-session knowledge extraction: sweep all conversation content
    try:
        all_msgs = _messages_to_dicts(messages)
        if last_response and last_response.content:
            all_msgs.append({"role": "assistant", "content": last_response.content})
        build_knowledge(
            messages=all_msgs,
            source_session_id=session_id,
        )
    except Exception as exc:
        log.warning("Knowledge build failed: %s", exc)

    # Save readline history
    try:
        readline.write_history_file(str(_history_file))
    except OSError:
        pass

    log.info("Chat session %s finalized", session_id)


def _messages_to_dicts(messages: list[Message]) -> list[dict[str, Any]]:
    """Convert Message objects to serializable dicts."""
    return [{"role": m.role, "content": m.content} for m in messages]


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    # Dispatch listing commands (no provider call needed)
    if dispatch_listing(args):
        return

    # Interactive chat mode
    if args.chat:
        asyncio.run(
            run_chat(
                provider_name=args.provider,
                model=args.model,
                temperature=args.temperature,
                max_tokens=args.max_tokens,
                session_id=args.session_id,
                verbose=args.verbose,
                allow_all=args.allow_all,
            )
        )
        return

    message = " ".join(args.message) if args.message else ""

    asyncio.run(
        run(
            provider_name=args.provider,
            model=args.model,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            message=message,
            verbose=args.verbose,
            allow_all=args.allow_all,
        )
    )


if __name__ == "__main__":
    main()
