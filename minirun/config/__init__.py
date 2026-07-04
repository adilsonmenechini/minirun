from pathlib import Path

from dotenv import load_dotenv

from minirun.log import get_logger

log = get_logger("config")


def load_env(env_path: str | None = None) -> None:
    if env_path:
        dotenv_path = Path(env_path)
    else:
        dotenv_path = find_dotenv()

    if dotenv_path and dotenv_path.is_file():
        log.info("Loading environment from %s", dotenv_path)
        load_dotenv(dotenv_path, override=True)
    else:
        log.debug("No .env file found, skipping")


def find_dotenv() -> Path | None:
    cwd = Path.cwd()
    for parent in [cwd] + list(cwd.parents):
        candidate = parent / ".env"
        if candidate.is_file():
            return candidate
    return None
