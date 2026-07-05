from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path
import readline  # noqa: F401 — line-editing for input()
import sys
import uuid
from typing import Any

from minirun.boot import init as boot_init
from minirun.cli.knowledge_commands import dispatch_knowledge_command
from minirun.log import get_logger
from minirun.memory import (
    ExtractionResult,
    KnowledgeExtractor,
    KnowledgeStore,
    PROVIDER_CALLED,
    RESPONSE_GENERATED,
    SESSION_STARTED,
    SUMMARY_GENERATED,
    build_knowledge,
)
from minirun.ports.provider import Message, Response
from minirun.runtime.context import build_memory_context
from minirun.runtime.events import emit_event, get_journal
from minirun.runtime.state import RuntimeState, RuntimeStateMachine
from minirun.runtime.harness import (
    bootstrap,
    finalize_session,
    get_provider,
)
from minirun.tools import registry
from minirun.workspace import Workspace

log = get_logger("cli")

HELP_TEXT = """
Chat commands:
  /exit, /quit              Exit the chat
  /session                  Show current session ID
  /help                     Show this help message
  /clear                    Clear the terminal screen
  !<command>                Execute a shell command (e.g. !ls -lha)
  /tools                    List registered tools
  /profiles                 List available profiles
  /commands                 List custom workspace commands
  /skills                   List installed skills
  /events, /journal [N]      Show last N journal events (default: 20)
  /events, /journal --session <id>  Show events for a specific session
  /events, /journal --type <type>   Show events of a specific type
  /knowledge list           List all stored facts
  /knowledge search <query> Search facts by keyword
  /knowledge delete <id>    Delete a specific fact by ID
  /knowledge prune          Remove all expired facts

Press Ctrl+C to exit at any time.
"""


def _list_tools() -> None:
    """Print all registered tools."""
    tools = registry.list_tools()
    if not tools:
        print("No tools registered.")
        return
    print(f"Registered tools ({len(tools)}):")
    for t in tools:
        desc = t.get("description", "")
        source = t.get("_source", "builtin")
        print(f"  {t['name']:30s}  {desc}")
        if source and source != "builtin":
            print(f"  {'':30s}  [{source}]")


def _list_profiles() -> None:
    """Print available profiles from workspace."""
    ws = Workspace()
    profiles = ws.discover_profiles()
    if not profiles:
        print("No profiles found in workspace/profiles/.")
        return
    print(f"Available profiles ({len(profiles)}):")
    for p in profiles:
        desc = p.get("description", "")
        print(f"  @{p['name']:30s}  {desc}  ({p['format']}) {p['path']}")


def _list_skills() -> None:
    """Print installed skills from workspace."""
    ws = Workspace()
    skills = ws.discover_skills()
    if not skills:
        print("No skills found in workspace/skills/.")
        return
    print(f"Installed skills ({len(skills)}):")
    for s in skills:
        desc = s.get("description", "")
        print(f"  {s['name']:30s}  {desc}  ({s['format']}) {s['path']}")


def _list_commands() -> None:
    """Print custom commands from workspace."""
    ws = Workspace()
    commands = ws.discover_commands()
    if not commands:
        print("No commands found in workspace/commands/.")
        return
    print(f"Custom commands ({len(commands)}):")
    for c in commands:
        desc = c.get("description", "")
        print(f"  {c['name']:30s}  {desc}  ({c['format']}) {c['path']}")


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
    parts = raw_cmd[len("/events"):].strip().split()
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

    # Build filter description for header
    desc_parts: list[str] = []
    if session_filter:
        desc_parts.append(f"session={session_filter[:8]}")
    if type_filter:
        desc_parts.append(f"type={type_filter}")
    filter_desc = f" ({', '.join(desc_parts)})" if desc_parts else ""

    print(f"\nRecent journal events{filter_desc} ({len(events)}):")
    print("─" * 100)
    for ev in events:
        ts = ev.get("timestamp", "?")
        # Trim timestamp to seconds readability
        if len(ts) > 19:
            ts = ts[:19]
        etype = ev.get("event_type", "?")
        sid = ev.get("session_id", "?")[:8]
        eid = ev.get("id", "?")[:8]
        payload = ev.get("payload", {}) or {}
        # Build a one-line summary from the payload
        payload_preview = ""
        if isinstance(payload, dict) and payload:
            # Pick the most interesting keys
            preview_keys = ["tool", "provider", "profile", "content_length",
                           "num_messages", "decision", "reason", "prompt"]
            parts_preview: list[str] = []
            for k in preview_keys:
                v = payload.get(k)
                if v is not None:
                    v_str = str(v)[:40]
                    parts_preview.append(f"{k}={v_str}")
            if parts_preview:
                payload_preview = " | " + ", ".join(parts_preview)
        print(f"  {ts}  {etype:20s}  {sid}  [{eid}]{payload_preview}")
    print()


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

    provider = get_provider(
        name=provider_name,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    if not message:
        print("No message provided. Use: minirun <prompt>", file=sys.stderr)
        sys.exit(1)

    # Generate session ID for persistence
    session_id = str(uuid.uuid4())
    log.info("Starting session %s", session_id)
    emit_event(session_id, SESSION_STARTED, {
        "provider": provider_name or "default",
        "model": model or "default",
    })

    # ── Explicit state machine ───────────────────────────────────────
    sm = RuntimeStateMachine(session_id)
    log.debug("Runtime state machine initialized: %s", sm)

    # BUILD_CONTEXT
    sm.transition(RuntimeState.BUILD_CONTEXT)

    # Initialize knowledge store for context injection
    knowledge_store = KnowledgeStore()

    # Build memory context from past session summaries and knowledge
    memory_ctx = build_memory_context(
        prompt=message,
        knowledge_store=knowledge_store,
    )
    messages: list[Message] = []
    if memory_ctx:
        log.info("Found relevant past context for prompt")
        messages.append(Message(role="system", content=memory_ctx))
    messages.append(Message(role="user", content=message))

    # CALL_PROVIDER
    sm.transition(RuntimeState.CALL_PROVIDER)

    emit_event(session_id, PROVIDER_CALLED, {
        "num_messages": len(messages),
        "provider": provider_name or "default",
        "model": model or "default",
    })
    response = await provider.complete(messages)
    emit_event(session_id, RESPONSE_GENERATED, {
        "content_length": len(response.content or ""),
        "finish_reason": getattr(response, "finish_reason", None),
    })
    sys.stdout.write(response.content)
    if response.content and not response.content.endswith("\n"):
        sys.stdout.write("\n")

    # UPDATE_CONTEXT → FINALIZE
    sm.transition(RuntimeState.UPDATE_CONTEXT)
    sm.transition(RuntimeState.FINALIZE)

    # Persist session and generate summary
    await finalize_session(
        session_id=session_id,
        prompt=message,
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
    emit_event(session_id, SESSION_STARTED, {
        "provider": provider_name or "default",
        "model": model or "default",
        "resumed": False,
    })

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

    # ── Persistent readline history ────────────────────────────────
    _HISTORY_FILE = Path.home() / ".minirun_history"
    _HISTORY_MAX = 1000
    try:
        readline.read_history_file(str(_HISTORY_FILE))
        readline.set_history_length(_HISTORY_MAX)
    except FileNotFoundError:
        pass  # First time — no history yet

    print(f"     minirun chat \n \nsession {session_id[:8]}...")
    print("Type /help for commands, /exit to quit.")
    if resumed:
        print(f"(Resumed {len(messages)} previous messages)")

    try:
        while True:
            try:
                user_input = input("\nyou: ").strip()
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
                elif cmd == "/clear":
                    os.system("clear" if sys.platform != "win32" else "cls")
                    continue
                elif cmd.startswith("/events") or cmd.startswith("/journal"):
                    # Normalize /journal → /events for _list_events parsing
                    normalized = cmd.replace("/journal", "/events", 1)
                    _list_events(normalized)
                    continue
                else:
                    print(f"Unknown command: {user_input}. Type /help for commands.")
                    continue

            # Execute shell commands (! prefix)
            if user_input.startswith("!"):
                shell_cmd = user_input[1:].strip()
                if not shell_cmd:
                    print("Usage: !<command>  (e.g. !ls -lha)")
                    continue
                print(f"$ {shell_cmd}")
                try:
                    rc = os.system(shell_cmd)
                    if rc != 0:
                        print(f"[Exit code: {rc}]")
                except Exception as exc:
                    print(f"Error executing command: {exc}")
                continue

            # Send message to provider
            messages.append(Message(role="user", content=user_input))

            # CALL_PROVIDER
            sm.transition(RuntimeState.CALL_PROVIDER)

            emit_event(session_id, PROVIDER_CALLED, {
                "num_messages": len(messages),
                "provider": provider_name or "default",
                "model": model or "default",
            })
            try:
                provider_response = await provider.complete(messages)
            except Exception as exc:
                log.error("Provider call failed: %s", exc)
                print(f"\nError: {exc}")
                messages.pop()  # Remove failed message
                continue

            # Print and accumulate response
            output = provider_response.content or ""
            emit_event(session_id, RESPONSE_GENERATED, {
                "content_length": len(output),
            })
            sys.stdout.write(output)
            if output and not output.endswith("\n"):
                sys.stdout.write("\n")

            messages.append(Message(role="assistant", content=output))

            # UPDATE_CONTEXT
            sm.transition(RuntimeState.UPDATE_CONTEXT)

            # Extract knowledge facts from the response
            try:
                profile_name = ""  # could be derived from the active profile
                result: ExtractionResult = knowledge_extractor.extract(
                    content=output,
                    source_session_id=session_id,
                    tags=[profile_name] if profile_name else None,
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
            emit_event(session_id, SUMMARY_GENERATED, {
                "prompt": first_prompt[:80],
            })
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
        readline.write_history_file(str(_HISTORY_FILE))
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
