<!--
  Sync Impact Report
  ==================
  Version change: (none) → v1.0.0 (initial), v1.0.0 → v1.1.0
  Principles: All 5 newly created from PLAN.md philosophy
    - I. Runtime > Framework (new)
    - II. Profiles > Agents (new)
    - III. Contracts > Magic (new)
    - IV. SQLite > Infrastructure (new)
    - V. Security by Policy (new)
  Added sections:
    - Development Workflow (NON-NEGOTIABLE) under Implementation Discipline
  Modified sections:
    - Implementation Discipline: added TDD-first, SDD, tooling requirements
  Removed sections: (none)
  Templates requiring updates:
    - .specify/templates/plan-template.md: ✅ reviewed — already generic, no change needed
    - .specify/templates/spec-template.md: ✅ reviewed — already generic, no change needed
    - .specify/templates/tasks-template.md: ✅ reviewed — already generic, no change needed
    - .specify/templates/checklist-template.md: ✅ reviewed — already generic, no change needed
    - .specify/templates/constitution-template.md: ✅ reviewed — template unchanged
    - .opencode/commands/speckit.*.md: ✅ reviewed — no agent-specific references found
  Follow-up TODOs: none
-->

# minirun Constitution

## Core Principles

### I. Runtime > Framework
This project is a **deterministic runtime** for executing specialized tasks with
LLMs — not an agent framework. The core is a single loop housed in
`runtime/harness.py`:
```
Parse Command → Load Profile → Load Memory → Build Prompt → Call Provider →
Execute Tool (if needed) → Continue → Persist Events → Return Response
```
No Agent, Planner, Supervisor, Critic, or Researcher abstractions MUST ever be
created. Every tool call is a deterministic, traceable step in this loop. If a
component cannot be expressed as a step in the loop, the architecture is wrong.

### II. Profiles > Agents
Profiles MUST be static configuration files (YAML or Markdown), not code
classes. Each profile defines a name, description, a list of allowed_tools, and
a system_prompt. The runtime injects the profile as context into the LLM prompt
— it does NOT instantiate "agent objects". Example profiles: `datadog`,
`terraform`, `sre`, `kubernetes`, `aws`. A profile is data, not behavior.

### III. Contracts > Magic
Every component MUST implement a clear, minimal interface.

- **Tools**: a `Tool` class with a `name` property and `async execute()` method.
  All tools in `tools/` (filesystem.py, shell.py, http.py, mcp.py) implement
  the same interface.
- **Providers**: a single `provider.complete(messages, tools)` interface defined
  in `providers/base.py`. Never let provider-specific types (Gemini message
  format, OpenAI chat objects, Anthropic content blocks) leak into the runtime.
- **Registry**: `tools/registry.py` provides discovery and invocation.

No magic imports, no dynamic class loading, no auto-discovery conventions.

### IV. SQLite > Infrastructure
Start with SQLite for all persistence. Memory hierarchy: **Session →
Summaries → Knowledge**. Tables: `sessions`, `messages`, `events`, `knowledge`.

Do NOT start with vector databases, embeddings, RAG pipelines, reflection
loops, or memory graphs. These MAY be evaluated and added later only if real
usage data proves them necessary. YAGNI applies strictly to all infrastructure
decisions.

### V. Security by Policy
Every tool invocation MUST pass through a Policy Engine before execution.
```
Tool Request → Policy Engine → Allowed? → Execute | Deny
```
Policies MUST be defined in YAML (`config/security.yaml`) specifying:
- `allowed_tools` — e.g., filesystem.read, datadog.incident
- `allowed_paths` — e.g., workspace/

Security is a first-class architectural concern enforced at runtime, not an
afterthought or documentation-only requirement.

## Architecture & Modularity

The codebase MUST be divided into exactly **8 top-level modules**:

```
minirun/
├── runtime/       # Core execution loop (harness.py)
├── profiles/      # Profile definitions (YAML/Markdown)
├── providers/     # LLM provider adapters (base.py, gemini.py, openai.py, anthropic.py)
├── tools/         # Tool implementations (filesystem.py, shell.py, http.py, mcp.py, registry.py)
├── memory/        # Persistence layer (SQLite: sessions, messages, events, knowledge)
├── security/      # Policy engine
├── config/        # settings.yaml + .env for secrets only
└── cli/           # Command-line interface
```

No additional top-level modules MUST be created without a constitutional
amendment. Configuration is separated from secrets: `config/settings.yaml` for
all non-sensitive configuration, `.env` for secrets only.

The CLI binary is named `minirun`. Usage pattern:
```
minirun @sre analyze terraform plan
minirun @datadog incident 12345
minirun @aws analyze cost
minirun @kubernetes inspect pod api-123
```

## Implementation Discipline

Implementation MUST follow the predefined sprint order. No skipping ahead.

1. **Sprint 1** — Runtime + Gemini provider + SQLite + Filesystem Tool
2. **Sprint 2** — Profiles + Command Parser + HTTP Tool
3. **Sprint 3** — MCP support + Policy Engine
4. **Sprint 4** — Domain integrations (Datadog, Terraform, Kubernetes)
5. **Sprint 5** — Memory system with Summaries

Contracts and interfaces MUST be defined BEFORE writing implementation code.
Never add a dependency without documented justification. Each sprint MUST
produce a working, testable increment before the next sprint begins.

### Development Workflow (NON-NEGOTIABLE)

Every feature implementation MUST follow this exact sequence:

1. **TDD First** — Write tests BEFORE implementation code. Red (test fails) →
   Green (minimal implementation) → Refactor cycle. No implementation code is
   written without a preceding failing test.
2. **SDD Second** — Security-Driven Development: before finalizing any code,
   evaluate for credential leaks, path traversal, command injection, and
   excessive tool permissions. Security review is part of every task, not a
   separate phase.
3. **Lint & Type Check** — Every change MUST pass:
   - `ruff check .` (zero warnings)
   - `pyright` (strict mode, zero errors)
4. **Dead Code Check** — `vulture . --min-confidence 65` MUST pass with zero
   undetected dead code below the confidence threshold.
5. **Test Gate** — All tests MUST pass (`pytest` with `pytest-asyncio`);
   coverage MUST be ≥ 65% for new code.

Any violation MUST block the commit. No exceptions, no `# noqa`, no `# type: ignore`
unless explicitly approved by the maintainer with a documented rationale.

## Governance

This constitution supersedes all other practices and development guidelines.

**Amendment procedure**:
1. Document the rationale for the change.
2. Submit for review and approval by the project maintainer.
3. Include a migration plan for any affected modules.
4. Update version according to SemVer and update `LAST_AMENDED_DATE`.

**Versioning policy**:
- MAJOR: backward-incompatible principle removals or redefinitions.
- MINOR: new principle or section added, materially expanded guidance.
- PATCH: clarifications, wording refinements, typo fixes.

**Compliance**: All plans and specifications MUST reference the constitution
principles they comply with. Plans MUST include a "Constitution Check" section.
The constitution is reviewed at the end of each sprint for any needed updates.

**Version**: 1.1.0 | **Ratified**: 2026-07-04 | **Last Amended**: 2026-07-04
