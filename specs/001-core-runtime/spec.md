# Feature Specification: Core Runtime

**Feature Branch**: `N/A`

**Created**: 2026-07-04

**Status**: Draft

**Input**: Project vision from `docs/PLAN.md` — Sprint 1 of minirun

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Run a task with a profile (Priority: P1)

An SRE engineer invokes minirun with a profile and a task description. The
runtime loads the profile configuration, sends the task to an LLM, and returns
a response — all within a single deterministic loop.

**Why this priority**: This is the foundational capability. Without this, no
other feature in the project delivers value. Every subsequent story depends on
the runtime loop being operational.

**Independent Test**: Can be fully tested by running minirun with a profile
(e.g., `minirun @sre analyze "describe the health of a pod"`) and observing a
coherent, non-error response returned to the user.

**Acceptance Scenarios**:

1. **Given** a profile named "sre" exists with a system prompt, **When** the
   user runs `minirun @sre analyze "describe the health of a Kubernetes pod"`,
   **Then** the runtime returns a response relevant to the task within a
   reasonable time.
2. **Given** the task includes a request to read a file from the workspace,
   **When** the LLM invokes the filesystem tool, **Then** the tool executes,
   the result is fed back to the LLM, and the final response incorporates the
   file content.

---

### User Story 2 — Persist and resume a session (Priority: P2)

An SRE engineer runs multiple related tasks within the same session. Messages
and events are persisted to local storage, allowing the user to continue the
conversation or review past interactions.

**Why this priority**: Persistence enables practical work flows — users need to
iterate on tasks without losing context. This separates a usable tool from a
throwaway REPL.

**Independent Test**: Can be fully tested by running two sequential tasks in
the same session, verifying the second task has awareness of the first.

**Acceptance Scenarios**:

1. **Given** a session exists with previous messages, **When** the user runs a
   new task referencing prior context (e.g., "expand on that last point"),
   **Then** the response shows awareness of the conversation history.
2. **Given** a completed session, **When** the user queries the list of past
   sessions, **Then** the session appears with its timestamp and summary.

---

### User Story 3 — No agent framework abstractions (Priority: P3)

A developer extending minirun should never encounter Agent, Planner,
Supervisor, Critic, or Researcher classes. The runtime loop is the only
execution model.

**Why this priority**: This is a non-negotiable architectural constraint from
the project constitution. It prevents accidental complexity from creeping into
the core.

**Independent Test**: Can be fully tested by inspecting the codebase for
forbidden patterns and running the loop with a debug trace that confirms no
abstractions beyond the runtime loop are involved.

**Acceptance Scenarios**:

1. **Given** the runtime source, **When** inspected, **Then** no Agent,
   Planner, Supervisor, Critic, or Researcher class or module exists.
2. **Given** a runtime execution, **When** the execution trace is recorded,
   **Then** every step maps directly to the loop: Build Context → Call
   Provider → Execute Tool → Persist → Return.

---

### Edge Cases

- What happens when the LLM provider returns an error (timeout, invalid
  response, authentication failure)? The user receives a clear error message.
- How does the runtime handle a tool call that fails mid-execution? The error
  is returned to the LLM, which may retry or report the failure to the user.
- What happens when no profile matching the requested name is found? The
  runtime returns an error listing available profiles.
- How does the system handle an empty task or whitespace-only input? The
  runtime returns a "task cannot be empty" error without calling the provider.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Users MUST be able to invoke a task with a profile name and a
  natural-language task description.
- **FR-002**: The runtime MUST load the profile configuration (system prompt,
  allowed tools) and inject it into the LLM context before calling the
  provider.
- **FR-003**: The runtime MUST execute exactly one deterministic loop per
  invocation: build context → call provider → execute tool if requested →
  continue or return.
- **FR-004**: When the LLM requests a tool execution, the runtime MUST execute
  the tool, feed the result back to the LLM, and continue the loop.
- **FR-005**: The runtime MUST persist every message and tool event to local
  storage before returning the final response.
- **FR-006**: Users MUST be able to list past sessions and view session
  summaries.
- **FR-007**: The runtime MUST return a clear error message if the provider
  cannot be reached or returns an unexpected error.
- **FR-008**: The runtime MUST return an error listing available profiles if
  the requested profile name does not exist.

### Key Entities *(include if feature involves data)*

- **Session**: A conversation boundary containing one or more related task
  invocations. Has a start time, end time, and summary.
- **Message**: A single exchange in a session — either a user task or an LLM
  response. Contains role, content, and timestamp.
- **Event**: A record of a tool execution within the loop. Contains tool name,
  input, output, success/failure status, and timestamp.
- **Profile**: A static configuration that defines the LLM's behavior for a
  specific domain (e.g., sre, datadog, kubernetes). Contains name, description,
  system prompt, and allowed tool list.
- **Tool**: A capability the LLM can invoke during execution. Has a name and
  produces structured output from structured input.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user can run a task with a profile and receive a relevant
  response within 30 seconds on a standard developer workstation.
- **SC-002**: A session with 10 sequential messages is fully persisted and
  retrievable after restarting the process.
- **SC-003**: A user viewing the session history can identify when each session
  occurred, what profile was used, and a summary of the conversation.
- **SC-004**: If the LLM provider is offline, the user receives a clear,
  actionable error message within 5 seconds — not a timeout hang.
- **SC-005**: No Agent, Planner, Supervisor, Critic, or Researcher concept
  exists anywhere in the delivered code.

## Assumptions

- The project is developed on a standard developer workstation with internet
  access to an LLM provider endpoint.
- The user has valid credentials for at least one LLM provider (Gemini as the
  initial default).
- The user is an SRE engineer or developer comfortable with command-line
  interfaces.
- The first LLM provider implementation may be limited in capabilities (e.g.,
  no streaming, no vision) — additional capabilities are added in later
  sprints.
- Only a filesystem tool is included in Sprint 1 — the shell tool, HTTP tool,
  and MCP come in later sprints.
- Profiles are defined as local YAML or Markdown files in a well-known
  directory — no remote profile registry in Sprint 1.
- The system runs locally, not as a service — multi-user support is out of
  scope for Sprint 1.
