from __future__ import annotations

import argparse
import asyncio
import sys

from minirun.boot import init as boot_init
from minirun.ports.provider import Message
from minirun.runtime.harness import get_provider


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


async def run(
    provider_name: str | None,
    model: str | None,
    temperature: float | None,
    max_tokens: int | None,
    message: str,
    verbose: int = 0,
) -> None:
    log_level = None
    if verbose >= 2:
        log_level = 10  # DEBUG
    elif verbose == 1:
        log_level = 20  # INFO
    boot_init(log_level=log_level)

    provider = get_provider(
        name=provider_name,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    if not message:
        print("No message provided. Use: minirun <prompt>", file=sys.stderr)
        sys.exit(1)

    messages = [Message(role="user", content=message)]
    response = await provider.complete(messages)
    sys.stdout.write(response.content)
    if response.content and not response.content.endswith("\n"):
        sys.stdout.write("\n")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    message = " ".join(args.message) if args.message else ""

    asyncio.run(
        run(
            provider_name=args.provider,
            model=args.model,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            message=message,
            verbose=args.verbose,
        )
    )


if __name__ == "__main__":
    main()
