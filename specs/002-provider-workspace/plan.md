# Implementation Plan: Provider and Workspace Setup

**Branch**: `N/A` | **Date**: 2026-07-04 | **Spec**: [spec.md](../spec.md)

**Input**: Feature specification from `specs/002-provider-workspace/spec.md`

## Summary

Add OpenAI and Anthropic as LLM providers with custom base URL support via `.env`
environment variables. Create a `workspace/` directory with `{memory, agents,
commands, skills}` subdirectories following Claude Code / OpenCode conventions.
Provider configuration supports flexible URL routing through API gateways.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: openai, anthropic, python-dotenv

**Storage**: Filesystem (`workspace/` tree), SQLite (`workspace/memory/`)

**Testing**: pytest + pytest-asyncio

**Target Platform**: macOS, Linux (developer workstation)

**Project Type**: CLI runtime (Python application)

**Performance Goals**: Provider response within 30s per task call (network-bound);
workspace creation under 1s

**Tooling**: ruff (lint), pyright (type check strict), vulture (dead code ≥65%)
**Constraints**: API keys in `.env` only (never in settings.yaml);
workspace path defaults to project root

**Scale/Scope**: Single-user local execution

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Runtime > Framework | ✅ PASS | No new abstractions — providers implement existing `base.py` interface |
| II. Profiles > Agents | ✅ PASS | Profiles remain static config; no agent objects created |
| III. Contracts > Magic | ✅ PASS | OpenAI and Anthropic adapters implement `provider.complete()` contract |
| IV. SQLite > Infrastructure | ✅ PASS | Workspace/memory uses SQLite as specified; no vector stores |
| V. Security by Policy | ✅ PASS | API keys in .env, workspace paths follow security.yaml patterns |
| Architecture (8 modules) | ✅ PASS | Providers go in `providers/`, workspace is runtime data, not a module |
| Implementation Discipline | ✅ PASS | Sprint 2 feature (matches constitution order) |

## Project Structure

### Documentation (this feature)

```text
specs/002-provider-workspace/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output — provider interface contract
└── tasks.md             # Phase 2 output (/speckit.tasks)
```

### Source Code (repository root)

```text
minirun/
├── providers/
│   ├── base.py          # Abstract provider interface (existing)
│   ├── gemini.py        # Existing Gemini provider
│   ├── openai.py        # NEW: OpenAI adapter
│   └── anthropic.py     # NEW: Anthropic adapter
├── config/
│   ├── settings.yaml    # Non-sensitive settings (existing)
│   └── .env.example     # NEW: provider API key template
├── cli/
│   └── main.py          # NEW: init command (workspace creation)
└── workspace/           # NEW: auto-created at first run
    ├── memory/
    ├── agents/
    ├── commands/
    └── skills/

tests/
├── providers/
│   ├── test_openai.py
│   ├── test_anthropic.py
│   └── test_base.py
├── test_workspace.py
└── test_dotenv.py
```

**Structure Decision**: Single project following the 8-module architecture from the
constitution. Providers extend existing `providers/` module. Workspace is a runtime
data directory, not a code module. All new code lives within established module
boundaries.

## Complexity Tracking

No constitution violations. Complexity tracking not required.
