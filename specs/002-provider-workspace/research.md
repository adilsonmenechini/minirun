# Research: Provider and Workspace Setup

## Phase 0 — Technology Decisions

### LLM Provider SDKs

**Decision**: Use official OpenAI and Anthropic Python SDKs.

**Rationale**:
- Both SDKs are mature, well-maintained, and provide native async support
- OpenAI SDK supports custom `base_url` parameter natively for API gateway routing
- Anthropic SDK supports custom `base_url` via client initialization
- Both have built-in retry, timeout handling, and error types

**Alternatives considered**:
- Custom HTTP client: unnecessary duplication — both SDKs handle
  authentication, retries, and streaming better than a custom wrapper
- LiteLLM library: adds abstraction layer that violates "Contracts > Magic"
  principle; also introduces unnecessary dependency

### Provider Interface (`providers/base.py`)

**Decision**: Follow existing Gemini adapter patterns; OpenAI and Anthropic
implement the same `provider.complete(messages, tools)` contract.

**Rationale**:
- Constitution Principle III (Contracts > Magic) mandates a single interface
- All providers must be interchangeable from the runtime's perspective
- Message format translation happens inside the adapter, never in the runtime

### Environment Variable Configuration

**Decision**: Use `python-dotenv` to load `.env`; provider-specific env vars:

```
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1      # Optional
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_BASE_URL=https://api.anthropic.com    # Optional
```

**Rationale**:
- `.env` files are language-agnostic standard for local secrets
- `python-dotenv` is the de facto Python standard (10M+ weekly downloads)
- Custom URL pattern matches how organizations deploy API gateways
- Falls back to provider default URL when env var is absent

### Workspace Directory Discovery

**Decision**: Runtime checks for `workspace/` at startup; creates if absent.
Path resolved relative to project root (where `.env` or `settings.yaml` lives).

**Rationale**:
- Mirror Claude Code / OpenCode conventions for familiarity
- No configuration needed — convention over configuration
- Subdirectory structure (`memory/`, `agents/`, `commands/`, `skills/`) matches
  established patterns for LLM tooling ecosystems

### Profile Loading from Workspace

**Decision**: Profile loader searches `workspace/agents/` in addition to
built-in `profiles/` directory. User profiles override built-in profiles with
the same name.

**Rationale**:
- Users need a place to add custom profiles without modifying the codebase
- Workspace profiles are ignored by version control (likely .gitignored)
- Override semantics: workspace > built-in (user intent over default)

### Formatting Configuration

**Decision**: Standard Python tooling:
- **Formatter**: Black (line-length 88)
- **Linter**: Ruff (replaces Flake8, isort, pyupgrade)
- **Type checker**: mypy (strict mode)
- **Pre-commit**: pre-commit hooks for all of the above

**Rationale**:
- Industry-standard Python tooling stack
- Ruff is significantly faster than alternatives
- Consistent with Claude Code / OpenCode project conventions
