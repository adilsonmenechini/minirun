# Provider Interface Contract

## Contract

Every LLM provider MUST implement the following interface defined in
`providers/base.py`:

```
async def complete(
    messages: list[Message],
    tools: list[Tool] | None = None
) -> Response
```

### Message Format

Messages use a canonical format — each adapter translates to/from its SDK's
native format internally:

```yaml
Message:
  role: "system" | "user" | "assistant" | "tool"
  content: str | list[ContentBlock]
  name: str | None        # Tool call name (for role="tool")
  tool_call_id: str | None # For correlating tool calls and results
```

### Tool Format

```yaml
Tool:
  name: str                # Unique identifier
  description: str         # What the tool does (LLM-facing)
  parameters: dict         # JSON Schema for tool arguments
  async def execute(input: dict) -> ToolResult
```

### Response Format

```yaml
Response:
  content: str             # LLM text response
  tool_calls: list[ToolCall] | None  # Tool invocations requested by LLM
  usage: Usage | None       # Token usage metadata

ToolCall:
  id: str                  # Unique call identifier
  name: str                # Tool name to execute
  arguments: dict           # Tool arguments

ToolResult:
  output: str              # Tool execution output
  success: bool            # Whether execution succeeded
  error: str | None        # Error message if failed
```

### Error Handling

Providers MUST raise typed exceptions for the following:

| Error | When | Recovery |
|-------|------|----------|
| `AuthenticationError` | Invalid or missing API key | User reconfigures .env |
| `RateLimitError` | Rate limit exceeded | Retry with backoff |
| `ConnectionError` | Custom URL unreachable | Verify URL in .env |
| `ModelNotFoundError` | Invalid model name | Check model availability |
| `ProviderError` | Unexpected API error | Return error to user |

### Configuration Contract

Each provider reads its configuration from environment variables following the
pattern:

```
<PROVIDER>_API_KEY       # Required for provider to be usable
<PROVIDER>_BASE_URL      # Optional; falls back to SDK default
```

Where `<PROVIDER>` is the uppercase provider name (e.g., `OPENAI`, `ANTHROPIC`).

## Adapters

### OpenAI Adapter (`providers/openai.py`)

- Uses `openai.OpenAI(api_key=..., base_url=...)` client
- Translates canonical `Message` format to OpenAI chat format
- Translates OpenAI response format to canonical `Response`
- Supports function/tool calling via OpenAI's `tools` parameter

### Anthropic Adapter (`providers/anthropic.py`)

- Uses `anthropic.Anthropic(api_key=..., base_url=...)` client
- Translates canonical `Message` format to Anthropic Messages API format
- Translates Anthropic response format to canonical `Response`
- Supports tool calling via Anthropic's `tools` parameter
- Handles Anthropic's content block structure (text, tool_use, tool_result)

### Gemini Adapter (`providers/gemini.py`)

- Existing adapter (Sprint 1) — kept as reference for the interface contract
- Follows same `provider.complete()` contract

## Testing Contract

Every adapter MUST pass the same contract tests:

1. **Given** a valid API key, **When** calling `complete()` with a simple
   message, **Then** return a `Response` with content.
2. **Given** an invalid API key, **When** calling `complete()`, **Then** raise
   `AuthenticationError`.
3. **Given** a custom base URL pointing to a compatible endpoint, **When**
   calling `complete()`, **Then** the request reaches the custom endpoint.
4. **Given** a tool definition, **When** the LLM requests the tool, **Then**
   return a `Response` with `tool_calls` populated.
