# Quickstart: Provider and Workspace Setup

## Prerequisites

- Python 3.11+
- API keys for the providers you want to test

## Setup

```bash
# Navigate to the project root
cd /path/to/minirun

# Install dependencies
pip install openai anthropic python-dotenv

# Configure provider credentials
cp .env.example .env
# Edit .env with your API keys:
#   OPENAI_API_KEY=sk-...
#   ANTHROPIC_API_KEY=sk-ant-...
```

## Validation Scenarios

### Scenario 1: Run a task with OpenAI

```bash
# Set OpenAI as the active provider
export OPENAI_API_KEY="sk-..."

# Run a task through the runtime
minirun @sre analyze "Describe what Kubernetes pod lifecycle looks like"
```

**Expected outcome**: A coherent response from the OpenAI model about
Kubernetes pod lifecycle.

---

### Scenario 2: Run a task with Anthropic

```bash
# Set Anthropic as the active provider
export ANTHROPIC_API_KEY="sk-ant-..."

# Run the same task
minirun @sre analyze "Describe what Kubernetes pod lifecycle looks like"
```

**Expected outcome**: A coherent response from the Anthropic model,
demonstrating equivalent capability for the same task.

---

### Scenario 3: Custom API URL via .env

```bash
# Edit .env:
# OPENAI_BASE_URL=https://gateway.internal.example.com/v1
# OPENAI_API_KEY=sk-...

# Run a task
minirun @sre analyze "Summarize this incident"
```

**Expected outcome**: The request reaches the custom URL instead of the default
OpenAI endpoint. Verify via proxy logs or network monitoring.

---

### Scenario 4: Workspace directory creation

```bash
# In a clean directory, run minirun for the first time
minirun @sre analyze "list available tools"

# Verify workspace structure
ls -la workspace/
# Expected: memory/  agents/  commands/  skills/
```

**Expected outcome**: The `workspace/` directory exists with all four
subdirectories. Subsequent runs use the existing workspace without
modifications.

---

### Scenario 5: Custom profile in workspace

```bash
# Create a custom profile
cat > workspace/agents/custom-sre.yaml << 'EOF'
name: custom-sre
description: Custom SRE specialist
allowed_tools:
  - filesystem.read
  - shell.exec
system_prompt: |
  You are a senior SRE with 15 years of experience.
  Answer concisely with specific commands.
EOF

# Use the custom profile
minirun @custom-sre analyze "Check disk usage"
```

**Expected outcome**: The runtime loads and uses the profile from
`workspace/agents/`. The response reflects the custom system prompt.

---

### Scenario 6: Error — Missing API key

```bash
# Clear provider env vars
unset OPENAI_API_KEY
unset ANTHROPIC_API_KEY

# Attempt to run a task
minirun @sre analyze "test"
```

**Expected outcome**: A clear error message indicating no provider is
configured, with instructions to set the relevant API key in `.env`.

---

### Scenario 7: Error — Unreachable custom URL

```bash
# Set an unreachable URL
export OPENAI_BASE_URL="https://nonexistent.example.com/v1"
export OPENAI_API_KEY="sk-test"

minirun @sre analyze "test"
```

**Expected outcome**: A connection error within 5 seconds, not a timeout hang.
Message indicates the custom URL could not be reached.

## Provider Interface Contract Reference

See [contracts/provider-interface.md](contracts/provider-interface.md) for the
full provider contract specification, including message format, tool format,
error types, and testing requirements for each adapter.
