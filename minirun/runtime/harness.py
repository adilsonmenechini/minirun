from __future__ import annotations

import os

from minirun.boot import init as boot_init
from minirun.log import get_logger
from minirun.ports.provider import BaseProvider
from minirun.providers import PROVIDERS
from minirun.workspace import Workspace

log = get_logger("runtime")


def bootstrap() -> None:
    boot_init()
    ws = Workspace()
    created = ws.init()
    log.info("Workspace bootstrapped (created=%s)", created)


def get_provider(
    name: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> BaseProvider:
    bootstrap()
    provider_name = (
        name
        or os.environ.get("LLM_PROVIDER", "openai")
    )
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
