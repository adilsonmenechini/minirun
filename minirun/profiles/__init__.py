"""Profile loading and discovery.

Profiles define agent personas (system prompts, allowed tools) and can be stored
in the workspace's agents/ directory or in a built-in profiles directory.
"""

from minirun.profiles.loader import discover_profiles, load_profile

__all__ = [
    "discover_profiles",
    "load_profile",
]
