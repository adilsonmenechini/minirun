# minirun

**Deterministic runtime for executing specialized tasks with LLMs.**

minirun is not a framework. It is a minimal, deterministic runtime that executes specialized tasks by loading profiles (not agents) and routing them through pluggable LLM providers. It follows a strict port/adapter architecture — the core has zero knowledge of any specific LLM API.

## Philosophy

```
Runtime  > Framework
Profiles > Agents
Events   > Conversations
Contracts > Magic
SQLite   > Infrastructure
Composition > Inheritance
```

## What minirun is NOT

minirun does not implement:
- Agent, Planner, Supervisor, Critic, Researcher, Reviewer
- LangChain, CrewAI, LangGraph, AutoGen
- RAG, Vector DB, Embeddings, Reflection, Memory Graph (yet)

Those can be added later. The core stays small.

## Architecture

```
minirun/
├── runtime/         # Core execution harness
├── providers/       # Port interface + facade
├── adapters/        # Concrete provider implementations (OpenAI, Anthropic)
├── ports/           # Abstract contracts (BaseProvider, Message, Tool, etc.)
├── profiles/        # Profile loading and discovery
├── config/          # Settings (settings.yaml + .env for secrets)
├── workspace/       # User workspace (memory/, agents/, commands/, skills/)
├── cli/             # Command-line interface
└── log/             # Structured logging
```

### Runtime

The runtime is the heart. It follows a simple loop:

```python
while True:
    context = build_context()
    response = provider.complete(context)
    if response.has_tool():
        tool.execute()
        continue
    break
```

### Provider Interface

Every LLM provider implements the same abstract contract:

```python
class BaseProvider(abc.ABC):
    async def complete(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Response: ...
```

**Current providers:**
- [OpenAI](https://openai.com) — `OpenAIProvider` (default model: `gpt-4o`)
- [Anthropic](https://anthropic.com) — `AnthropicProvider` (default model: `claude-sonnet-4-20250514`)

All providers include automatic retry with exponential backoff and proper error classification (AuthenticationError, RateLimitError, ConnectionError, ModelNotFoundError, ProviderError).

### Profiles (not Agents)

Profiles define what a persona can do — system prompt, allowed tools, preferred provider.

```
name: sre
description: Senior SRE specialized in incident response
allowed_tools:
  - incidents
  - monitors
  - logs
system_prompt: |
  You are a senior SRE. Analyze the situation and respond.
```

Profiles are stored as YAML or Markdown files in the workspace's `agents/` directory and are invoked via `@profile_name` syntax.

### Workspace

Upon first run, minirun creates a `workspace/` directory at the project root:

```
workspace/
├── memory/      # Session persistence (JSON files)
├── agents/      # User-defined profiles
├── commands/    # Custom CLI commands
└── skills/      # Extensions and capabilities
```

## Quick Start

### Installation

```bash
pip install minirun
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uv sync
```

### Configuration

Copy the example environment file and configure your LLM provider:

```bash
cp .env.example .env
```

Edit `.env`:

```
# Generic LLM config (used by all providers)
LLM_PROVIDER=openai
LLM_API_KEY=sk-your-api-key-here
LLM_BASE_URL=          # Optional: custom API endpoint
LLM_MODEL=gpt-4o
LLM_MAX_TOKENS=4096
```

**Precedence:** `.env` > `config/settings.yaml` > hardcoded defaults.

API keys MUST go in `.env` — never in `settings.yaml`.

### Usage

```bash
# Run a task with the default provider
minirun "summarize the current incident"

# Use a specific profile
minirun @sre "analyze the terraform plan"

# Specify provider and model explicitly
minirun --provider anthropic --model claude-opus-4-20250514 "explain this error"

# Continue an existing session
minirun abc123 "what was the root cause?"

# Verbose output
minirun -v "debug this issue"
minirun -vv "trace the execution"
```

#### CLI Options

| Option | Description |
|--------|-------------|
| `session_or_profile` | Session ID to resume, or `@profile` to use a persona |
| `message` | The prompt to send to the LLM |
| `--provider` | LLM provider: `openai` or `anthropic` |
| `--model` | Model identifier (overrides provider default) |
| `--temperature` | Sampling temperature |
| `--max-tokens` | Maximum output tokens |
| `-v` / `-vv` | Increase verbosity (INFO / DEBUG) |

### Session Persistence

minirun saves conversation state to `workspace/memory/sessions/`. Resume a session by passing its ID:

```bash
minirun abc123 "continue the analysis"
```

## Project Structure

```
.
├── pyproject.toml          # Project metadata and dependencies
├── .env.example            # Environment variable template
├── minirun/                # Core package
│   ├── __init__.py
│   ├── boot.py             # Initialization (logging, env, settings)
│   ├── log.py              # Structured logging setup
│   ├── runtime/
│   │   └── harness.py      # Execution bootstrap and provider resolution
│   ├── ports/
│   │   └── provider.py     # Abstract contracts (BaseProvider, Message, Tool, etc.)
│   ├── providers/
│   │   └── __init__.py     # Provider facade and re-exports
│   ├── adapters/
│   │   ├── openai.py       # OpenAI provider implementation
│   │   └── anthropic.py    # Anthropic provider implementation
│   ├── profiles/
│   │   ├── __init__.py
│   │   └── loader.py       # Profile discovery and loading
│   ├── config/
│   │   ├── __init__.py     # .env loading
│   │   ├── loader.py       # settings.yaml loading and merging
│   │   └── settings.yaml   # Default configuration
│   ├── workspace/
│   │   └── workspace.py    # Workspace directory management
│   └── cli/
│       └── main.py         # CLI argument parsing and entry point
├── specs/                  # Feature specifications
├── tests/                  # Test suite
└── workspace/              # User workspace (auto-created)
```

## Development

```bash
# Install with dev dependencies
uv sync --dev

# Run tests
uv run pytest

# Type checking
uv run pyright

# Linting
uv run ruff check
```

The project requires Python ≥ 3.11 and uses:
- [pytest](https://docs.pytest.org/) for testing
- [Ruff](https://docs.astral.sh/ruff/) for linting
- [Pyright](https://github.com/microsoft/pyright) for type checking
- [uv](https://docs.astral.sh/uv/) for package management

## License

[MIT](LICENSE)