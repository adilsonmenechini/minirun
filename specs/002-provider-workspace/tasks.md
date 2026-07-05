---

description: "Complete task list for Provider and Workspace Setup feature — includes original 45 completed tasks + remaining gaps"
---

# Tasks: Provider and Workspace Setup

**Input**: Design documents from `specs/002-provider-workspace/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US4, US5, US6)
- Include exact file paths in descriptions

## Path Conventions

- **Project root**: `minirun/` — top-level module
- **Test root**: `tests/` at repository root
- File paths are relative to project root unless absolute

---

## ✅ Phase 1: Setup (Shared Infrastructure) — COMPLETE

**Purpose**: Project initialization, dependency installation, and tooling config

- [x] T001 Create `providers/` directory with `__init__.py` in `minirun/providers/`
- [x] T002 [P] Add dependencies (`openai`, `anthropic`, `python-dotenv`) to `pyproject.toml`
- [x] T003 [P] Configure tooling: `ruff`, `pyright` (strict), `vulture` (min-confidence 65) with `pyproject.toml`
- [x] T004 Create `.env.example` with all provider env var templates
- [x] T005 [P] Create `tests/providers/` directory with `__init__.py`
- [x] T006 [P] Create `tests/workspace/` directory with `__init__.py`

---

## ✅ Phase 2: Foundational (Blocking Prerequisites) — COMPLETE

**Purpose**: Provider base interface and error types

- [x] T007 Write contract test for `provider.complete()` interface in `tests/providers/test_base.py`
- [x] T008 [P] Define `AuthenticationError`, `RateLimitError`, `ConnectionError`, `ModelNotFoundError`, `ProviderError` in `minirun/providers/base.py` (now `minirun/ports/provider.py`)
- [x] T009 Define `Message`, `Tool`, `Response`, `ToolCall`, `ToolResult`, `Usage` data classes in `minirun/ports/provider.py`
- [x] T010 Define abstract `BaseProvider` class with `async def complete()` method in `minirun/ports/provider.py`
- [x] T011 Write contract test verifying each error type is importable from `minirun/providers` in `tests/providers/test_base.py`
- [x] T012 Run `ruff check .` and `pyright` — fix all violations

---

## ✅ Phase 3: User Story 1 — OpenAI and Anthropic Providers (P1) — COMPLETE

**Story Goal**: Users can run tasks with either OpenAI or Anthropic as the LLM provider.

- [x] T013 [P] [US1] Write test for OpenAI adapter in `tests/providers/test_openai.py`
- [x] T014 [P] [US1] Write test for Anthropic adapter in `tests/providers/test_anthropic.py`
- [x] T015 [US1] Write test for OpenAI invalid key → `AuthenticationError`
- [x] T016 [US1] Write test for Anthropic invalid key → `AuthenticationError`
- [x] T017 [US1] Implement `OpenAIProvider` in `minirun/providers/openai.py` (now `minirun/adapters/openai.py`)
- [x] T018 [US1] Implement `AnthropicProvider` in `minirun/providers/anthropic.py` (now `minirun/adapters/anthropic.py`)
- [x] T019 [US1] Register both providers in `minirun/providers/__init__.py`
- [x] T020 [US1] Wire provider selection into `minirun/runtime/harness.py`
- [x] T021 Run `ruff`, `pyright`, `vulture`, `pytest` — fix all violations
- [x] T022 SDD review: audit provider code for credential leaks

---

## ✅ Phase 4: User Story 2 — Custom API URL via .env (P1) — COMPLETE

**Story Goal**: Users can set a custom base URL for any provider via .env.

- [x] T023 [P] [US2] Write test: custom `OPENAI_BASE_URL` in `tests/providers/test_openai.py`
- [x] T024 [P] [US2] Write test: custom `ANTHROPIC_BASE_URL` in `tests/providers/test_anthropic.py`
- [x] T025 [US2] Write test: default URL when no custom URL set
- [x] T026 [US2] Write test: unreachable URL raises `ConnectionError`
- [x] T027 [US2] Add `python-dotenv` loading in `minirun/config/__init__.py`
- [x] T028 [US2] Update `OpenAIProvider` to read `OPENAI_BASE_URL` in `minirun/adapters/openai.py`
- [x] T029 [US2] Update `AnthropicProvider` to read `ANTHROPIC_BASE_URL` in `minirun/adapters/anthropic.py`
- [x] T030 Run `ruff`, `pyright`, `vulture`, `pytest` — fix all violations
- [x] T031 SDD review: audit `.env` loading for path traversal

---

## ✅ Phase 5: User Story 3 — Workspace Directory (P2) — COMPLETE

**Story Goal**: minirun auto-creates `workspace/{memory,agents,commands,skills}` on first run.

- [x] T032 [US3] Write test: workspace init creates subdirectories in `tests/workspace/test_workspace.py`
- [x] T033 [US3] Write test: existing workspace is not overwritten
- [x] T034 [US3] Write test: profile from `workspace/profiles/` is discoverable
- [x] T035 [US3] Write test: workspace profile overrides built-in profile
- [x] T036 [US3] Implement workspace init in `minirun/workspace/workspace.py`
- [x] T037 [US3] Implement profile discovery in `minirun/workspace/workspace.py`
- [x] T038 [US3] Wire workspace bootstrap into `minirun/runtime/harness.py`
- [x] T039 Run `ruff`, `pyright`, `vulture`, `pytest` — fix all violations
- [x] T040 SDD review: audit workspace file operations

---

## ✅ Phase 6: Polish and Cross-Cutting — COMPLETE

**Purpose**: Final linter pass, security hardening, dead code removal

- [x] T041 [P] Run `ruff` across full project — zero warnings
- [x] T042 [P] Run `pyright` strict mode — zero errors
- [x] T043 [P] Run `vulture` — zero undetected dead code
- [x] T044 [P] Run `pytest` — all pass; coverage ≥ 65%
- [x] T045 Final SDD review: credential leaks, path traversal, command injection

---

## ✅ Phase 6b: Architecture Refactoring (Post-Spec) — COMPLETE

**Purpose**: Port/adapter restructuring, logging, model/temperature/retry, env vars

- [x] T046 [P] Create `minirun/ports/` and `minirun/adapters/` modules in `minirun/ports/provider.py` and `minirun/adapters/openai.py` / `minirun/adapters/anthropic.py`
- [x] T047 [P] Create structured logging module in `minirun/log.py`
- [x] T048 Instrument all modules with logging (config, adapters, workspace, harness)
- [x] T049 Update `minirun/providers/__init__.py` as facade re-exporting from ports + adapters
- [x] T050 Delete old `minirun/providers/base.py`, `minirun/providers/openai.py`, `minirun/providers/anthropic.py`
- [x] T051 Add `model`, `temperature`, `max_retries` params to `BaseProvider.complete()` + adapters
- [x] T052 Add `call_with_retry()` with exponential backoff in `minirun/ports/provider.py`
- [x] T053 Add model env var defaults (`OPENAI_MODEL`, `ANTHROPIC_MODEL`)
- [x] T054 Add `max_tokens` param + env vars (`OPENAI_MAX_TOKENS`, `ANTHROPIC_MAX_TOKENS`)
- [x] T055 Move side-effect code from `config/__init__.py` to `minirun/boot.py` with explicit `init()`
- [x] T056 Run full gates — 68 tests, 93% coverage

---

## Pending Phases (Work Remaining)

---

## Phase 7: User Story 4 — settings.yaml Configuration (P2)

**Story Goal**: Users can configure non-secret provider settings via `config/settings.yaml`. The runtime respects `.env` > `settings.yaml` precedence for all provider-related settings.

**Independent Test**: Create `config/settings.yaml` with `OPENAI_MODEL: gpt-4o-mini`. Verify provider uses model from settings.yaml. Then add `OPENAI_MODEL=gpt-4o-turbo` to `.env`. Verify `.env` value takes precedence.

**Spec References**: FR-008, spec.md Edge Cases (line 108-110), data-model.md (line 61), constitution.md (line 100-101)

- [x] T057 [P] [US4] Create `config/settings.yaml` with provider section template in `minirun/config/settings.yaml`
- [x] T058 [P] [US4] Implement YAML config loader in `minirun/config/loader.py`
- [x] T059 [US4] Implement config merge logic (`.env` > `settings.yaml` > defaults) in `minirun/config/loader.py`
- [x] T060 [US4] Wire config loader into `minirun/boot.py` — load `settings.yaml` during `init()`
- [x] T061 [P] [US4] Write tests for settings.yaml loading in `tests/config/test_settings.py`
- [x] T062 [P] [US4] Write tests for `.env` > YAML precedence in `tests/config/test_settings.py`
- [x] T063 [P] [US4] Write tests for missing settings.yaml fallback in `tests/config/test_settings.py`

**Checkpoint**: `config/settings.yaml` is loaded at startup, merged with `.env`, and provider respects the merged config.

---

## Phase 8: User Story 5 — CLI Entry Point (P1)

**Story Goal**: Users can invoke minirun from the command line with `minirun [options]` supporting `--provider`, `--model`, `--temperature` arguments. The CLI wires into the full bootstrap + provider lifecycle.

**Independent Test**: Run `minirun --provider openai --model gpt-4o --temperature 0.5` and verify the provider is created with those parameters.

**Spec References**: constitution.md (lines 103-109), plan.md (line 28), spec.md acceptance scenarios

- [x] T064 [P] [US5] Create `minirun/cli/main.py` with `argparse` argument parser
- [x] T065 [US5] Implement CLI → harness wiring: parse args, call `boot_init()`, create provider, invoke `complete()`
- [x] T066 [P] [US5] Add `--provider` argument (choices: openai, anthropic)
- [x] T067 [P] [US5] Add `--model` argument (string, overrides env/default)
- [x] T068 [P] [US5] Add `--temperature` argument (float, overrides env/default)
- [x] T069 [P] [US5] Add `--max-tokens` argument (int, overrides env/default)
- [x] T070 [US5] Wire CLI to `minirun/runtime/harness.py` — get_provider passes CLI overrides
- [x] T071 [P] [US5] Write tests for CLI argument parsing in `tests/cli/test_main.py`
- [x] T072 [P] [US5] Write tests for CLI → provider wiring in `tests/cli/test_main.py`

**Checkpoint**: `minirun --help` shows all options. `minirun --provider anthropic --model claude-3-haiku` creates the correct provider.

---

## Phase 9: User Story 6 — Skill & Command Discovery (P2)

**Story Goal**: The runtime discovers skills from `workspace/skills/` and commands from `workspace/commands/`, completing the FR-007 requirement.

**Independent Test**: Place a `.md` file in `workspace/skills/` and a `.sh` file in `workspace/commands/`. Call `discover_skills()` and `discover_commands()` — both return the discovered entries.

**Spec References**: FR-007 (line 129-130), spec.md acceptance scenario 3 (line 93-94), data-model.md (lines 26-27, 32)

- [x] T073 [P] [US6] Implement `discover_skills()` in `minirun/workspace/workspace.py` — scans `workspace/skills/` for `.md`, `.yaml`, `.yml` files
- [x] T074 [P] [US6] Implement `discover_commands()` in `minirun/workspace/workspace.py` — scans `workspace/commands/` for `.sh`, `.py` files
- [x] T075 [US6] Add `skills` and `commands` return fields to `Workspace` class
- [x] T076 [P] [US6] Write test: `discover_skills()` returns empty when no skills directory in `tests/workspace/test_workspace.py`
- [x] T077 [P] [US6] Write test: `discover_skills()` finds `.md` and `.yaml` files in `tests/workspace/test_workspace.py`
- [x] T078 [P] [US6] Write test: `discover_commands()` finds `.sh` scripts in `tests/workspace/test_workspace.py`

**Checkpoint**: `workspace.discover_skills()` returns files from `workspace/skills/`. `workspace.discover_commands()` returns files from `workspace/commands/`.

---

## Phase 10: User Story 7 — Profile Module (P2)

**Story Goal**: A dedicated `minirun/profiles/` module exists per the constitution's 8-module architecture, with profile loading, parsing, and workspace/profiles/ override logic.

**Independent Test**: Place a YAML profile in `workspace/profiles/` and a built-in profile with the same name in `minirun/profiles/`. Load via `profiles.load("name")` — the workspace version wins.

**Spec References**: constitution.md (line 91), data-model.md (lines 44-46), spec.md FR-006 (line 127-128)

- [x] T079 [P] [US7] Create `minirun/profiles/__init__.py` with profile registry and loader
- [x] T080 [US7] Implement `load(name)` — search `workspace/profiles/` first, then `minirun/profiles/`
- [ ] T081 [US7] Implement `list_profiles()` — merge built-in and workspace profiles
- [x] T082 [P] [US7] Write test: workspace profile overrides built-in in `tests/profiles/test_profiles.py`
- [x] T083 [P] [US7] Write test: profile not found raises clear error (returns None)
- [ ] T084 [P] [US7] Write test: invalid YAML profile raises parse error

**Checkpoint**: `profiles.load("sre")` returns the correct profile. Workspace profiles override built-ins.

---

## Phase 11: Full Gates + Integration

**Purpose**: Final verification pass across ALL changes and a real integration test.

**Independent Test**: Run the full test suite + linting + type checking + dead code detection. Then run an integration smoke test with a mock HTTP server simulating a provider API.

- [x] T085 [P] Run `ruff` across full project — zero warnings
- [x] T086 [P] Run `pyright` strict across full project — zero errors (pre-existing SDK stubs excluded)
- [x] T087 [P] Run `vulture` across full project — exit 0
- [x] T088 [P] Run `pytest` — all tests pass; verify coverage ≥ 65%
- [x] T089 Write integration E2E test in `tests/integration/test_e2e.py` — mock provider flow through harness, both OpenAI and Anthropic
- [ ] T090 Final SDD review: scan all changed files for credential leaks, path traversal, command injection

**Checkpoint**: All gates pass. Integration test proves end-to-end provider flow.

---

## Summary

| Phase | Story | Tasks | Priority | Status |
|-------|-------|-------|----------|--------|
| 1 | Setup | T001–T006 | — | ✅ Complete |
| 2 | Foundational | T007–T012 | — | ✅ Complete |
| 3 | US1: Providers | T013–T022 | P1 | ✅ Complete |
| 4 | US2: Custom URL | T023–T031 | P1 | ✅ Complete |
| 5 | US3: Workspace | T032–T040 | P2 | ✅ Complete |
| 6 | Polish | T041–T045 | — | ✅ Complete |
| 6b | Architecture Refactor | T046–T056 | — | ✅ Complete |
| **7** | **US4: settings.yaml** | **T057–T063** | **P2** | **✅ Complete** |
| **8** | **US5: CLI** | **T064–T072** | **P1** | **✅ Complete** |
| **9** | **US6: Skills/Commands** | **T073–T078** | **P2** | **✅ Complete** |
| **10** | **US7: Profile Module** | **T079–T084** | **P2** | **70% Complete** |
| **11** | **Gates + Integration** | **T085–T090** | **—** | **80% Complete** |

**Total tasks**: 90 (85 ✅ complete, 5 ❌ pending)

**Suggested MVP scope**: Phase 8 (CLI) is the highest-value remaining item — it makes the tool actually usable from the command line.

## Dependency Graph

```
Phase 7 (settings.yaml) ──┐
                           ├──→ Phase 11 (Gates + Integration)
Phase 8 (CLI) ────────────┘
                           │
Phase 9 (Skill/Cmd) ──────┤
                           │
Phase 10 (Profile module) ─┘
```

**Note**: Phases 7–10 are independent of each other and can run in parallel. All must complete before Phase 11.

## Parallel Execution Examples

**Per Phase 7 (settings.yaml)**:
- T057 and T058 can run in parallel
- T061, T062, T063 can run in parallel

**Per Phase 8 (CLI)**:
- T066, T067, T068, T069 can run in parallel
- T071 and T072 can run in parallel

**Per Phase 9 (Skill/Cmd)**:
- T073 and T074 can run in parallel
- T076, T077, T078 can run in parallel

**Per Phase 10 (Profile module)**:
- T079 and T082 can run in parallel (impl + test)
- T083 and T084 can run in parallel
