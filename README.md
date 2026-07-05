<div align="center">

# ⚡ minirun

**Minimal Runtime for Operational AI**

*Not a framework. A deterministic runtime that executes specialized profiles through pluggable LLM providers.*

<br>

[![Python ≥3.11](https://img.shields.io/badge/python-≥3.11-blue?style=flat&logo=python)](https://python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green?style=flat)](LICENSE)
[![Ruff](https://img.shields.io/badge/linting-ruff-purple?style=flat)](https://docs.astral.sh/ruff/)
[![Pyright](https://img.shields.io/badge/type_check-pyright_strict-2a7de1?style=flat)](https://github.com/microsoft/pyright)

</div>

---

## 📚 Documentation

| Document | Description |
|----------|-------------|
| **[ARCHITECTURE.md](docs/ARCHITECTURE.md)** | Components, contracts, and execution flow |
| **[PRD.md](docs/PRD.md)** | Product requirements, personas, and roadmap |
| **[ADR-001](adr/ADR-001-runtime.md)** | Single Runtime decision |
| **[ADR-002](adr/ADR-002-provider.md)** | Provider Abstraction decision |
| **[ADR-003](adr/ADR-003-profiles.md)** | Profiles instead of Agents decision |
| **[ADR-004](adr/ADR-004-tools.md)** | Tool Registry + MCP decision |
| **[ADR-005](adr/ADR-005-memory.md)** | SQLite + Summaries decision |
| **[ADR-006](adr/ADR-006-security.md)** | Default-Deny Security decision |

---

## 🧭 Philosophy

```
Runtime  > Framework         |  Profiles > Agents
Events   > Conversations     |  Contracts > Magic
SQLite   > Infrastructure    |  Composition > Inheritance
```

minirun is **not**:
- An agent framework (no Agent, Planner, Supervisor, Critic)
- LangChain, CrewAI, LangGraph, or AutoGen
- A multi-agent orchestrator
- A vector database, RAG pipeline, or embedding service

minirun **is**:
- A lightweight runtime for operational AI workflows
- Specialized profiles executed through a deterministic loop
- Provider-agnostic (OpenAI, Anthropic, or any LLM)
- Secure by default (every tool call passes through policy)

---

## 🏗️ Architecture

```
CLI
 ↓
Runtime ───→ Provider ───→ Tool Registry ───→ Memory (SQLite)
 ↓              ↓                ↓
Profiles     OpenAI/Anthropic   Policy Engine
```

```
minirun/
├── runtime/      # Bootstrap, provider resolution, memory finalization
├── ports/        # Abstract contracts (BaseProvider, Message, ToolCall)
├── providers/    # Provider resolution facade
├── adapters/     # OpenAI, Anthropic implementations
├── tools/        # Tool Registry, HTTP client, MCP client manager
├── security/     # Policy Engine — evaluate every tool call
├── memory/       # Session summaries + SQLite KnowledgeIndex
├── profiles/     # Profile discovery & loading (YAML/Markdown)
├── config/       # settings.yaml + .env (secrets only)
├── workspace/    # User workspace (memory/, profiles/, commands/, skills/)
├── cli/          # Argument parser & entry point
└── log/          # Structured logging
```

### 🔄 The Runtime Loop

```python
while True:
    context = build_context()
    response = provider.complete(context)
    if response.has_tool():
        policy.check(response.tool)  # default-deny
        tool.execute()
        continue
    break
```

On startup, `bootstrap()` initializes:

```
bootstrap()
├── boot_init()         → logging, .env, settings.yaml
├── Workspace.init()    → workspace/{memory,profiles,commands,skills}/
├── PolicyEngine()      → config/security.yaml (default-deny)
└── ToolRegistry        → http.get, http.post
```

---

## 🎯 Features

### 🔌 Pluggable Providers

Every LLM provider implements a single abstract contract:

```python
class BaseProvider(abc.ABC):
    async def complete(
        self, messages, tools=None,
        model=None, temperature=None, max_tokens=None,
    ) -> Response: ...
```

| Provider | Default Model | Status |
|----------|--------------|--------|
| [OpenAI](https://openai.com) | `gpt-4o` | ✅ Production |
| [Anthropic](https://anthropic.com) | `claude-sonnet-4-20250514` | ✅ Production |

Automatic retry with exponential backoff. Error classification: `AuthenticationError`, `RateLimitError`, `ConnectionError`, `ModelNotFoundError`, `ProviderError`.

### 📋 Profiles (not Agents)

Static configuration files — Markdown with frontmatter YAML. Profiles can configure MCP servers for tool extensibility.

```yaml
---
name: sre
description: Senior SRE specialized in incident response
allowed_tools:
  - filesystem.read
  - http.get
  - mcp.server.query
mcp_servers:
  - name: datadog-mcp
    transport: stdio
    command: npx
    args: ["@datadog/mcp-server"]
---
You are a senior SRE. Analyze the situation and respond.
```

Invoke via `@profile_name` syntax:

```bash
minirun @sre "analyze the terraform plan"
minirun @datadog "investigate incident 12345"
minirun @terraform "review this plan"
```

### 🔒 Security by Policy

Every tool invocation passes through the **Policy Engine** before execution. Default-deny: if a tool isn't in `allowed_tools`, it's denied.

```yaml
# config/security.yaml
policy:
  allowed_tools:    [filesystem.read, http.get, http.post]
  denied_tools:     [filesystem.write, shell.exec]
  allowed_paths:    [workspace/, /tmp/minirun/]
  allowed_domains:  [*.datadoghq.com, api.github.com]
```

### 🧠 Memory & Context

After each session, minirun automatically:
1. Generates a bullet summary via the LLM
2. Writes a markdown file to `workspace/memory/sessions/summaries/`
3. Indexes metadata in local SQLite

On the next run, relevant past summaries are retrieved by keyword and injected as system context — zero-config continuity.

### 🔗 MCP Support

Connect to external tools via [Model Context Protocol](https://modelcontextprotocol.io). Supports `stdio` and `tcp` transports, configured per-profile.

```yaml
# profiles/sre.md
---
name: sre
description: Senior SRE incident response
allowed_tools:
  - filesystem.read
  - http.get
mcp_servers:
  - name: datadog-mcp
    transport: stdio
    command: npx
    args: ["@datadog/mcp-server"]
    env:
      DD_API_KEY: "${DD_API_KEY}"
---
You are a senior SRE. Analyze the situation and respond.
```

Invoke via `@profile_name` syntax with MCP servers auto-connected:

```bash
minirun @sre "investigate incident 12345"
```

### 💬 Interactive Chat

```
minirun --chat                           # Start interactive session
minirun --chat --session-id abc-123      # Resume previous session
```

Chat commands: `/exit`, `/quit`, `/help`, `/session`

---

## 🚀 Quick Start

### Install

```bash
pip install minirun
# or
uv sync
```

### Configure

```bash
cp .env.example .env
```

```env
LLM_PROVIDER=openai
LLM_API_KEY=sk-your-key-here
LLM_MODEL=gpt-4o
LLM_MAX_TOKENS=4096
```

> **Precedence:** `.env` > `config/settings.yaml` > hardcoded defaults.
> API keys MUST go in `.env` — never in `settings.yaml`.

### Use

```bash
# Single task
minirun "summarize the current incident"

# With profile
minirun @sre "analyze the terraform plan"

# Interactive mode
minirun --chat

# Explicit provider & model
minirun --provider anthropic --model claude-sonnet-4-20250514 "explain this error"

# Bypass policy (dev only)
minirun --allow-all "run a diagnostic script"

# List resources
minirun --profiles
minirun --tools
minirun --commands
```

### CLI Options

| Flag | Description |
|------|-------------|
| `message` | Prompt to send to the LLM |
| `--provider` | LLM provider: `openai` or `anthropic` |
| `--model` | Model identifier |
| `--chat` | Start interactive chat session |
| `--session-id` | Resume an existing session by ID |
| `--temperature` | Sampling temperature |
| `--max-tokens` | Maximum output tokens |
| `--allow-all` | Bypass policy enforcement (default: deny) |
| `--tools` | List registered tools and exit |
| `--profiles` | List available profiles and exit |
| `--skills` | List installed skills and exit |
| `--commands` | List custom commands and exit |
| `-v` / `-vv` | Verbosity: INFO / DEBUG |

---

## 📁 Project Structure

```
minirun/
├── runtime/         # Bootstrap, loop, policy, memory finalization
├── ports/           # Abstract contracts
├── providers/       # Provider facade
├── adapters/        # OpenAI, Anthropic implementations
├── tools/           # Registry, HTTP, MCP client
├── security/        # Policy Engine (default-deny)
├── memory/          # SQLite + session summaries
├── profiles/        # Profile discovery & parsing
├── config/          # settings.yaml + .env loader
├── workspace/       # User workspace abstraction
├── cli/             # CLI entry point
└── docs/            # Architecture, PRD, ADRs
```

---

## 🛠️ Development

```bash
uv sync --dev                  # Install dev dependencies
uv run pytest -v               # Run tests
uv run pyright                 # Type check (strict mode)
uv run ruff check .            # Lint
```

**Stack:** Python ≥ 3.11 · [pytest](https://docs.pytest.org/) + [pytest-asyncio](https://pytest-asyncio.readthedocs.io/) · [Ruff](https://docs.astral.sh/ruff/) · [Pyright](https://github.com/microsoft/pyright) (strict) · [uv](https://docs.astral.sh/uv/)

### Implementation Status

| Sprint | Feature | Status |
|--------|---------|--------|
| 1 | Core Runtime | ✅ |
| 2 | Multi-Provider + Workspace | ✅ |
| 3 | MCP + Policy Engine + HTTP Tool | ✅ |
| 4 | Domain Integrations (Workspace MCP) | ✅ |
| 5 | Memory Summaries + KnowledgeIndex | ✅ |
| 6 | Interactive Chat + Session Resume | ✅ |
| 7 | Filesystem Tools (read, grep, glob) | ✅ |
| 8 | Docs: ARCHITECTURE, PRD, ADRs | ✅ |

---

<div align="center">

**MIT License** · Built for SRE engineers who need LLMs without the framework tax

</div>
