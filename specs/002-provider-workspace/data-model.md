# Data Model: Provider and Workspace Setup

## Entities

### Provider

| Field | Type | Description | Validation |
|-------|------|-------------|------------|
| `name` | string | Provider identifier (`openai`, `anthropic`) | Must match one of registered names |
| `api_key` | string | Authentication credential | Loaded from `.env`; never stored in code |
| `base_url` | string (optional) | Custom API endpoint URL | Must be valid URL if set; falls back to SDK default |
| `model` | string | Model identifier (e.g., `gpt-4`, `claude-3`) | Set per profile/request |

**Relationships**:
- A `Provider` implements the `provider.complete(messages, tools)` contract
- A `Profile` references which `Provider` to use
- `Provider` config is loaded from `.env`, never from profile YAML

### Workspace

| Field | Type | Description | Validation |
|-------|------|-------------|------------|
| `root` | path | Absolute path to workspace directory | Must be a writable directory |
| `memory` | path | `{root}/memory/` — session persistence (SQLite) | Created automatically |
| `agents` | path | `{root}/agents/` — user-defined profiles | Created automatically |
| `commands` | path | `{root}/commands/` — custom CLI commands | Created automatically |
| `skills` | path | `{root}/skills/` — user extensions | Created automatically |

**Relationships**:
- `Workspace` is a runtime data directory, not a code module
- `Workspace.agents` is a secondary profile source (after built-in `profiles/`)
- `Workspace.memory` holds the SQLite database files for session persistence

### Agent Profile (in workspace context)

| Field | Type | Description | Validation |
|-------|------|-------------|------------|
| `name` | string | Profile identifier used with `@name` | Must match `[a-zA-Z0-9_-]+` |
| `provider` | string (optional) | Which provider this profile uses | If absent, uses default from config |
| `description` | string | Human-readable purpose | Informational |
| `allowed_tools` | list[string] | Tools this profile may invoke | Must be subset of registered tools |
| `system_prompt` | string | LLM system instructions | Required |

**Relationships**:
- Profiles in `workspace/profiles/` override built-in profiles with same name
- Profiles in `workspace/profiles/` follow the same YAML format as built-in profiles

### Provider Config (.env)

| Variable | Example | Required | Description |
|----------|---------|----------|-------------|
| `OPENAI_API_KEY` | `sk-...` | Yes (for OpenAI) | OpenAI API key |
| `OPENAI_BASE_URL` | `https://gateway.example.com/v1` | No | Custom OpenAI endpoint |
| `ANTHROPIC_API_KEY` | `sk-ant-...` | Yes (for Anthropic) | Anthropic API key |
| `ANTHROPIC_BASE_URL` | `https://gateway.example.com/anthropic` | No | Custom Anthropic endpoint |

**Validation Rules**:
- If `OPENAI_API_KEY` is set but empty, treat as unconfigured
- If `OPENAI_BASE_URL` is set, it must be a valid URL
- Secrets are never logged, written to files, or exposed in error messages
- `.env` values take precedence over `config/settings.yaml` for provider settings

## State Transitions

### Provider Lifecycle

```
Unconfigured ──(set env vars)──> Configured ──(validate key)──> Ready
                                       │                            │
                                       └──(missing/invalid key)────┘
                                                    │
                                                    ▼
                                              Error State
```

### Workspace Lifecycle

```
Not Created ──(first run)──> Created ──(subsequent runs)──> Ready
                                   │
                                   └──(already exists)──────> Ready
```

## Validation Rules (from requirements)

1. Provider must be configured before use (FR-001, FR-002)
2. Custom URL must be valid or absent — never malformed (FR-003)
3. Workspace must be created only if absent — never overwrite existing content
   (FR-005, Edge Cases)
4. Workspace profile load order: workspace/profiles/ > built-in profiles/
   (FR-006)
5. `.env` takes precedence over `settings.yaml` for provider settings (FR-008)
