"""ANSI color helpers for modern CLI output.

Zero dependencies — uses raw ANSI escape codes. Designed for the
miniRUN philosophy: minimal, efficient, no cruft.
"""

from __future__ import annotations

import re
import sys

# ── ANSI codes ──────────────────────────────────────────────────────────

_RESET = "\033[0m"

_BOLD = "\033[1m"
_DIM = "\033[2m"

_FG_BLACK = "\033[30m"
_FG_RED = "\033[31m"
_FG_GREEN = "\033[32m"
_FG_YELLOW = "\033[33m"
_FG_BLUE = "\033[34m"
_FG_MAGENTA = "\033[35m"
_FG_CYAN = "\033[36m"
_FG_WHITE = "\033[37m"
_FG_GRAY = "\033[90m"

_BG_RED = "\033[41m"
_BG_GREEN = "\033[42m"
_BG_YELLOW = "\033[43m"
_BG_BLUE = "\033[44m"
_BG_GRAY = "\033[100m"


# ── Flag ────────────────────────────────────────────────────────────────

def _supports_color() -> bool:
    """Check if the terminal supports ANSI color."""
    if not sys.stdout.isatty():
        return False
    if sys.platform == "win32":
        # Windows Terminal and new consoles support ANSI
        return True
    return True  # All modern Unix terminals support ANSI


_USE_COLOR = _supports_color()


def color(text: str, *codes: str) -> str:
    """Wrap text in ANSI color codes (no-op if terminal doesn't support color)."""
    if not _USE_COLOR or not codes:
        return text
    return f"{''.join(codes)}{text}{_RESET}"


# ── Convenience helpers ─────────────────────────────────────────────────

def dim(text: str) -> str:
    return color(text, _DIM)


def red(text: str) -> str:
    return color(text, _FG_RED)


def green(text: str) -> str:
    return color(text, _FG_GREEN)


def yellow(text: str) -> str:
    return color(text, _FG_YELLOW)


def blue(text: str) -> str:
    return color(text, _FG_BLUE)


def cyan(text: str) -> str:
    return color(text, _FG_CYAN)


def magenta(text: str) -> str:
    return color(text, _FG_MAGENTA)


def gray(text: str) -> str:
    return color(text, _FG_GRAY)


def success(text: str) -> str:
    return color(text, _FG_GREEN)


def error(text: str) -> str:
    return color(text, _FG_RED, _BOLD)


def info(text: str) -> str:
    return color(text, _FG_CYAN)


def header(text: str) -> str:
    return color(text, _BOLD, _FG_WHITE)


# ── Prompt builder ──────────────────────────────────────────────────────

# ── ANSI-safe padding ────────────────────────────────────────────────

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def pad(text: str, width: int) -> str:
    """Pad visible text to width, ignoring invisible ANSI escape codes.

    Without this helper, ``f"{color(text):30s}"`` would pad to 30 *visible
    + ANSI* characters, breaking column alignment in terminal output.

    Args:
        text: The (possibly ANSI-colored) string.
        width: Desired visible character width.

    Returns:
        The text padded with spaces to achieve the target visible width.
    """
    visible = _ANSI_RE.sub("", text)
    return text + " " * max(0, width - len(visible))


# ── Prompt builder ──────────────────────────────────────────────────────

def build_prompt(
    profile_name: str | None = None,
    session_id: str | None = None,
) -> str:
    """Build a context-aware prompt label.

    When a profile is active, the prompt shows the profile name as the
    speaker.  Otherwise it shows ``you``.

    Examples::

        >>> build_prompt()
        'you: '
        >>> build_prompt(profile_name="sre")
        'sre: '
        >>> build_prompt(session_id="abc12345")
        'you: '
    """
    label = profile_name or "you"
    return f"{color(label, _FG_MAGENTA if profile_name else _FG_CYAN)}: "
