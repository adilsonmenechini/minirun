# Execution Journal — Plan

> **Central concept:** Every execution step is recorded as an immutable event in a SQLite-backed journal. The journal is the source of truth for observability, audit, replay, and knowledge extraction.

## Why the Execution Journal Matters

The Execution Journal is **not** a secondary concern or a debugging aid — it is a **first-class architectural pillar** that transforms minirun from a simple LLM client into an auditable, observable runtime for operational AI.

Without it, every interaction is ephemeral. With it:

- **Audit trail** — Every tool call, policy decision, and response is recorded with causal chains, session ID, and timestamp. No black boxes.
- **Replay** — Any session can be reconstructed from its event stream. Debug by replaying the exact sequence of events.
- **Metrics** — Count events by type to measure latency, error rates, tool usage, and provider costs.
- **Knowledge foundation** — The journal feeds the Knowledge Store. Facts extracted from successful sessions are anchored to their originating events.
- **Troubleshooting** — Policy denials, provider failures, and tool errors are all events. A single query shows the full failure chain.

## Architecture

```text
Runtime State Machine
    │
    ├── State transitions ──────► EventJournal
    ├── Profile load             ► EventJournal
    ├── Provider call            ► EventJournal
    ├── Tool request             ► EventJournal
    ├── Policy check             ► EventJournal (allow / deny / confirm)
    ├── Tool execution           ► EventJournal
    ├── Response generated       ► EventJournal
    └── Summary generated        ► EventJournal
                                    │
                                    ▼
                             SQLite (WAL mode)
                             workspace/memory/journal.sqlite
```

### Data Flow

```
emit(session_id, event_type, payload, parent_id)
    │
    ├── session_id  ── UUID of the session (partition key)
    ├── event_type  ── One of the EVENT_TYPES constants
    ├── payload     ── JSON-serialisable dict (tool name, params, latency, etc.)
    └── parent_id   ── Optional UUID of causal parent event (causality chain)
```

### Causal Chains

The `parent_id` field creates causal chains across events:

```
session_started
    └── profile_loaded
            └── provider_called
                    ├── tool_requested
                    │       └── tool_denied        (policy blocked it)
                    │       └── tool_executed      (policy allowed it)
                    └── response_generated
                            └── summary_generated
```

These chains allow tracing a tool execution failure back through policy checks, provider calls, and profile loading — all with a single SQL query.

## Event Types

| Constant | Event String | Emitted When | Payload Fields |
|----------|-------------|--------------|----------------|
| `SESSION_STARTED` | `session_started` | A new session begins | `provider`, `model`, `resumed` |
| `PROFILE_LOADED` | `profile_loaded` | A profile is activated with MCP | `profile`, `mcp_servers` |
| `PROVIDER_CALLED` | `provider_called` | LLM provider is invoked | `num_messages`, `provider`, `model` |
| `TOOL_REQUESTED` | `tool_requested` | A tool invocation is evaluated | `tool`, `params`, `decision` |
| `TOOL_DENIED` | `tool_denied` | Policy engine denied the tool | `tool`, `reason` |
| `TOOL_CONFIRMATION_REQUIRED` | `tool_confirmation_required` | Tool requires user confirmation | `tool`, `reason`, `params` |
| `TOOL_EXECUTED` | `tool_executed` | Tool execution completed | `tool`, `result` (truncated) |
| `RESPONSE_GENERATED` | `response_generated` | Provider returned a response | `content_length`, `finish_reason` |
| `SUMMARY_GENERATED` | `summary_generated` | Session summary was created | `prompt` |
| `STATE_TRANSITION` | `state_transition` | State machine changed state | `from`, `to`, `count` |

### Event Types Frozenset

All valid event types are stored in the `EVENT_TYPES` frozenset at `minirun/memory/journal/journal.py`. The frozenset is used for validation (not yet enforced, but available for schema-level event type constraints in future iterations).

## Schema

### `events` table (SQLite, WAL mode)

```sql
CREATE TABLE IF NOT EXISTS events (
    id          TEXT PRIMARY KEY,          -- UUID v4
    session_id  TEXT NOT NULL,             -- session partition key
    event_type  TEXT NOT NULL,             -- one of EVENT_TYPES
    timestamp   TEXT NOT NULL,             -- ISO-8601 UTC
    payload     TEXT NOT NULL DEFAULT '{}', -- JSON
    parent_id   TEXT                        -- causal parent event UUID
);

CREATE INDEX IF NOT EXISTS idx_events_session   ON events(session_id);
CREATE INDEX IF NOT EXISTS idx_events_type      ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp DESC);
```

## Query Patterns

### Recent events (across all sessions)

```python
journal.get_recent_events(limit=20)
```

### Events for a specific session

```python
journal.get_session_events(session_id="abc-123")
```

### Events of a specific type

```python
journal.get_events_by_type(event_type="tool_denied")
```

### Count events (optionally filtered by type)

```python
journal.count_events()                        # total
journal.count_events("provider_called")       # by type
```

## Integration with Existing Components

### With the State Machine

Every `RuntimeStateMachine.transition()` call emits a `STATE_TRANSITION` event. This means the event journal contains a complete audit of state machine execution:

```
IDLE → BUILD_CONTEXT → CALL_PROVIDER → EXECUTE_TOOL → UPDATE_CONTEXT → FINALIZE
```

Each transition logs `from`, `to`, and transition count, enabling precise troubleshooting of runtime loops.

### With the Policy Engine

The `check_tool_permission()` function in `minirun/runtime/harness.py` emits:

1. `TOOL_REQUESTED` — every tool evaluation (with decision value)
2. `TOOL_DENIED` — if decision is DENY or DENY_WITH_REASON
3. `TOOL_CONFIRMATION_REQUIRED` — if decision is REQUIRES_CONFIRMATION

This provides a complete audit trail of every policy decision.

### With the Knowledge Store

After session finalisation, `build_knowledge()` extracts facts from the full conversation. Each fact is stored with its originating `source_session_id`, linking knowledge back to the session's event chain for traceability.

### With the CLI

The CLI provides two entry-points for querying the journal:

- `/events [N]` — last N events (default 20)
- `/journal [N]` — alias for `/events`
- `/events --session <id>` — events for a specific session
- `/events --type <type>` — events of a specific type

## Storage

The journal lives at `workspace/memory/journal.sqlite` relative to the project root, or at the path provided to the `EventJournal` constructor.

```
workspace/
└── memory/
    ├── journal.sqlite           ← Execution Journal (SQLite, WAL)
    ├── sessions/
    │   ├── index.sqlite         ← Summary index (SQLite)
    │   ├── summaries/           ← Markdown summary files
    │   └── <session_id>.json    ← Session message dumps
    ├── knowledge.sqlite         ← Knowledge Store (SQLite)
    └── knowledge/               ← Knowledge artifacts
```

## Lifecycle

```
bootstrap()
    │
    ├── boot_init()              — logging, .env, settings.yaml
    ├── Workspace.init()         — create workspace directories
    ├── PolicyEngine()           — load config/security.yaml
    ├── init_journal()           — CREATE first EventJournal instance
    │
    ▼
Runtime execution loop
    │
    ├── emit(SESSION_STARTED)
    ├── emit(PROVIDER_CALLED)
    ├── emit(TOOL_REQUESTED)
    ├── emit(TOOL_EXECUTED) or TOOL_DENIED or TOOL_CONFIRMATION_REQUIRED
    ├── emit(RESPONSE_GENERATED)
    ├── emit(STATE_TRANSITION)    — on every state change
    │
    ▼
Session finalisation
    │
    ├── emit(SUMMARY_GENERATED)
    └── build_knowledge()        — facts linked to session_id
```

## Future Directions

### Event-Driven Knowledge Consolidation

Instead of extracting knowledge only at session end, a background consumer could process events in real-time:

- `TOOL_EXECUTED` events → extract operational knowledge (command output, API responses)
- `RESPONSE_GENERATED` events → extract reasoning patterns
- `TOOL_DENIED` events → learn policy boundaries

### Event Replay

A replay mode could consume events from the journal to reconstruct a session without calling the LLM provider again — useful for debugging, post-mortem, and regression testing.

### Metrics Pipeline

Events can be aggregated into time-series metrics:

```python
# Example: tool latency percentiles
SELECT event_type, COUNT(*) as count,
       AVG(json_extract(payload, '$.latency_ms')) as avg_latency
FROM events
WHERE event_type = 'tool_executed'
GROUP BY event_type;
```

### Event Subscription / Webhook

Future iterations could support streaming events to external systems (Datadog, PagerDuty, Slack) for real-time monitoring of runtime operations.
