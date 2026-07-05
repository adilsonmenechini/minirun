# ADR-003: Profiles Instead of Agents

**Status:** ✅ Accepted (2026-07-04)

---

## Context

O projeto precisava de um mecanismo para especializar o comportamento do runtime para diferentes domínios (SRE, Datadog, Terraform, Kubernetes). As alternativas consideradas:

1. **Agent classes**: criar classes `DatadogAgent`, `TerraformAgent`, etc., cada uma com lógica específica
2. **Plugin system**: agents como plugins carregados dinamicamente
3. **Profiles estáticos**: arquivos YAML/Markdown com configuração declarativa

Agent classes foram rejeitadas porque:
- Criam acoplamento entre domínio e código
- Cada novo domínio requer deploy de código
- Dificultam auditoria — comportamento está no código, não na configuração
- O review do projeto explicitamente diz "Profiles > Agents"

## Decision

**Adotar profiles como arquivos estáticos (Markdown com frontmatter YAML)** em vez de classes de agentes.

```yaml
---
name: datadog
description: "Datadog SRE specialist"
allowed_tools:
  - filesystem.read
  - http.get
  - datadog-mcp.query_logs
mcp_servers:
  - name: datadog-mcp
    transport: stdio
    command: npx
    args: ["-y", "@datadog/mcp-server"]
---
# System prompt
You are a Datadog SRE specialist...
```

O runtime não sabe o que é um "Datadog agent" — ele apenas carrega o profile e injeta o system prompt. Toda a especialização vem da configuração.

## Consequences

**Positivas:**
- Novo domínio = novo arquivo `.md` em `workspace/profiles/` — sem código novo
- Profiles podem ser versionados, revisados, e auditados como qualquer outro arquivo de configuração
- Usuários não-técnicos podem criar profiles editando YAML
- O runtime permanece genérico e reutilizável
- Fácil de listar, buscar, e comparar profiles

**Negativas:**
- Profiles não podem conter lógica condicional — todo o comportamento vem do system prompt + tools
- Não é possível "herdar" ou "compor" profiles (ex: @sre que inclui @datadog + @terraform)
- Validação é limitada — um profile com YAML inválido é silenciosamente ignorado (log warning)

## Compliance

- `minirun/profiles/loader.py` — descoberta e parsing de profiles em `workspace/profiles/`
- `minirun/profiles/__init__.py` — exporta `discover_profiles()`, `load_profile()`, `parse_frontmatter()`
- `workspace/profiles/` — diretório com profiles `datadog.md`, `terraform.md`, `sre.md`, `example.md`
- Profiles usam frontmatter YAML com `name`, `description`, `allowed_tools`, `mcp_servers`
- O termo "Agent" aparece em `WorkspaceAgent` no código — pendente de renomeação para `WorkspaceProfile`
