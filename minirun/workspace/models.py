"""Workspace data models for profiles, skills, agents, and commands."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from minirun.log import get_logger

log = get_logger("workspace.models")


@dataclass
class MCPServerConfig:
    """Configuration for an MCP server connection."""

    name: str
    transport: Literal["stdio", "tcp"]
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    host: str | None = None
    port: int | None = None


@dataclass
class WorkspaceProfile:
    """Workspace profile loaded from workspace/profiles/*.md frontmatter."""

    name: str
    description: str = ""
    allowed_tools: list[str] = field(default_factory=list)
    system_prompt: str = ""
    mcp_servers: list[MCPServerConfig] = field(default_factory=list)

    @staticmethod
    def from_file(path: Path) -> WorkspaceProfile:
        import yaml

        content = path.read_text(encoding="utf-8")
        if not content.startswith("---"):
            raise ValueError(f"Profile {path} missing frontmatter (---)")

        parts = content.split("---", 2)
        if len(parts) < 3:
            raise ValueError(f"Profile {path} has invalid frontmatter format")

        frontmatter = yaml.safe_load(parts[1])
        system_prompt = parts[2].strip() if len(parts) > 2 else ""

        if not isinstance(frontmatter, dict):
            raise ValueError(f"Profile {path} frontmatter must be a YAML object")

        # Parse mcp_servers — support both dict-of-dicts and list-of-dicts
        raw_servers = frontmatter.get("mcp_servers", [])
        mcp_servers: list[MCPServerConfig] = []
        if isinstance(raw_servers, dict):
            raw_servers = [{"name": k, **v} for k, v in raw_servers.items()]
        for server_data in raw_servers:
            if not isinstance(server_data, dict):
                continue
            mcp_servers.append(
                MCPServerConfig(
                    name=server_data.get("name", ""),
                    transport=server_data.get("transport", "stdio"),
                    command=server_data.get("command"),
                    args=server_data.get("args"),
                    env=server_data.get("env"),
                    host=server_data.get("host"),
                    port=server_data.get("port"),
                )
            )

        return WorkspaceProfile(
            name=frontmatter.get("name", path.stem),
            description=frontmatter.get("description", ""),
            allowed_tools=frontmatter.get("allowed_tools", []),
            system_prompt=system_prompt,
            mcp_servers=mcp_servers,
        )

    def apply_extensions(
        self,
        extensions: list[WorkspaceProfileOverride],
    ) -> WorkspaceProfile:
        """Merge matching profile extensions into this profile.

        For each extension targeting this profile (``ext.profile == self.name``):

        - **instructions** (Step 3.2): appended to ``system_prompt``, separated
          by a blank line.
        - **allowed_tools** (Step 3.3): appended to ``allowed_tools``. Duplicates
          are NOT added again.

        Args:
            extensions: List of profile extensions from
                ``workspace/profiles/extensions/*.yaml``.

        Returns:
            A new ``WorkspaceProfile`` with merged data (original is unchanged).
        """
        merged = WorkspaceProfile(
            name=self.name,
            description=self.description,
            allowed_tools=list(self.allowed_tools),
            system_prompt=self.system_prompt,
            mcp_servers=list(self.mcp_servers),
        )

        seen_tools = set(self.allowed_tools)
        extra_prompts: list[str] = []

        for ext in extensions:
            if ext.profile != self.name:
                continue

            if ext.instructions:
                extra_prompts.append(ext.instructions)

            for tool in ext.allowed_tools:
                if tool not in seen_tools:
                    merged.allowed_tools.append(tool)
                    seen_tools.add(tool)

            log.debug(
                "Applied extension '%s' to profile '%s' (%d tools added)",
                ext.name,
                self.name,
                len(ext.allowed_tools),
            )

        if extra_prompts:
            merged.system_prompt = (
                self.system_prompt + "\n\n" + "\n\n".join(extra_prompts)
            )

        return merged


@dataclass
class SkillTool:
    """A tool exposed by a skill."""

    name: str
    description: str = ""
    input_schema: dict[str, object] | None = None
    handler: str = ""


@dataclass
class WorkspaceSkill:
    """User-defined skill from workspace/skills/*.yaml."""

    name: str
    description: str = ""
    version: str = "1.0.0"
    timeout: int | None = None  # FR-011: configurable execution timeout (default 30)
    tools: list[SkillTool] = field(default_factory=list)

    @staticmethod
    def from_file(path: Path) -> WorkspaceSkill:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"Skill {path} must be a YAML object")

        tools: list[SkillTool] = []
        for tool_data in data.get("tools", []):
            if isinstance(tool_data, dict):
                tools.append(
                    SkillTool(
                        name=tool_data.get("name", ""),
                        description=tool_data.get("description", ""),
                        input_schema=tool_data.get("input_schema"),
                        handler=tool_data.get("handler", ""),
                    )
                )

        return WorkspaceSkill(
            name=data.get("name", path.stem),
            description=data.get("description", ""),
            version=data.get("version", "1.0.0"),
            timeout=data.get("timeout"),
            tools=tools,
        )


@dataclass
class WorkspaceProfileOverride:
    """Profile override from workspace/profiles/*.yaml.

    Wraps a base profile with additional instructions
    and tool restrictions.
    """

    name: str
    description: str = ""
    profile: str = ""
    instructions: str = ""
    allowed_tools: list[str] = field(default_factory=list)

    @staticmethod
    def from_file(path: Path) -> WorkspaceProfileOverride:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"Profile override {path} must be a YAML object")

        return WorkspaceProfileOverride(
            name=data.get("name", path.stem),
            description=data.get("description", ""),
            profile=data.get("profile", ""),
            instructions=data.get("instructions", ""),
            allowed_tools=data.get("allowed_tools", []),
        )


@dataclass
class WorkspaceTool:
    """A tool exposed by a workspace skill or profile."""

    name: str
    description: str = ""
    input_schema: dict[str, object] | None = None
    handler: str = ""


@dataclass
class WorkspaceCommand:
    """User-defined command from workspace/commands/*."""

    name: str
    type: str
    path: str
    description: str = ""
    args_schema: dict[str, object] | None = None

    @staticmethod
    def from_file(path: Path) -> WorkspaceCommand:
        """Create a WorkspaceCommand from a file path.

        Supports:
          - .md files with YAML frontmatter (name, description, type)
          - .sh shell scripts
          - .py Python scripts
        """
        suffix = path.suffix

        if suffix == ".md":
            from minirun.profiles.loader import parse_frontmatter

            fm = parse_frontmatter(path)
            name = fm.get("name", path.stem) if fm else path.stem
            desc = fm.get("description", "") if fm else ""
            cmd_type = fm.get("type", "shell") if fm else "shell"
            return WorkspaceCommand(
                name=name,
                type=cmd_type,
                path=str(path),
                description=desc,
            )

        if suffix == ".py":
            cmd_type = "python"
        else:
            cmd_type = "shell"

        return WorkspaceCommand(
            name=path.stem,
            type=cmd_type,
            path=str(path),
        )
