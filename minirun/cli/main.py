from __future__ import annotations

import argparse
import asyncio
import os
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
)
from minirun.ports.provider import Message, Response
from minirun.runtime.harness import (
    bootstrap,
    build_memory_context,
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

    response = await provider.complete(messages)
    sys.stdout.write(response.content)
    if response.content and not response.content.endswith("\n"):
        sys.stdout.write("\n")

    # Persist session and generate summary
    await finalize_session(
        session_id=session_id,
        prompt=message,
        messages=messages,
        response=response,
        provider=provider,
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

            try:
                provider_response = await provider.complete(messages)
            except Exception as exc:
                log.error("Provider call failed: %s", exc)
                print(f"\nError: {exc}")
                messages.pop()  # Remove failed message
                continue

            # Print and accumulate response
            output = provider_response.content or ""
            sys.stdout.write(output)
            if output and not output.endswith("\n"):
                sys.stdout.write("\n")

            messages.append(Message(role="assistant", content=output))

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
        except Exception as exc:
            log.warning("Failed to finalize session: %s", exc)

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
