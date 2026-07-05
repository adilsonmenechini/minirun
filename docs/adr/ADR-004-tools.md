# ADR-004: Tool Registry + MCP Integration

**Status:** ✅ Accepted (2026-07-04)

---

## Context

O runtime precisa executar ferramentas (tools) invocadas pelo LLM durante a conversação. Essas ferramentas podem ser:

1. **Built-in**: implementadas no próprio runtime (http.get, filesystem.read)
2. **MCP**: expostas por servidores externos via Model Context Protocol
3. **Skill**: definidas em arquivos YAML no workspace

As alternativas consideradas:

1. **Funções soltas**: cada tool é uma função Python importada diretamente pelo runtime
2. **Registry centralizado**: tools são registradas em um dicionário central com lookup por nome
3. **MCP-only**: todas as tools vêm de servidores MCP, sem tools built-in

## Decision

**Adotar um Tool Registry centralizado** com suporte a tools built-in + MCP.

```python
registry = ToolRegistry()
registry.register("http.get", execute_fn, description="...")
registry.register("filesystem.read", execute_fn, description="...")

# Execução
result = registry.execute("http.get", {"url": "..."})
```

Servidores MCP são conectados via `MCPClientManager`, que descobre tools dinamicamente e as disponibiliza através do registry.

## Consequences

**Positivas:**
- Lookup de tools é O(1) — dicionário em memória
- Tools podem vir de múltiplas fontes (built-in, MCP, skills) com o mesmo mecanismo de execução
- Registry pode ser inspecionado via `minirun --tools`
- MCP permite integração com qualquer ferramenta externa sem modificar o runtime
- Suporte a transporte stdio (subprocesso) e tcp (conexão remota)

**Negativas:**
- Registry não faz validação de schema de parâmetros — a validação é responsabilidade de cada tool
- MCP adiciona dependência (`mcp>=1.0.0`) e complexidade de conexão (reconexão, timeout)
- Tools MCP dependem de servidores externos — indisponibilidade do servidor quebra a tool

## Compliance

- `minirun/tools/registry.py` — `ToolRegistry` (register, get, list, execute) + `MCPClientManager` (connect, list_tools, call_tool)
- `minirun/tools/http.py` — implementação das tools http.get e http.post
- `minirun/tools/filesystem.py` — implementação das tools filesystem.read/write/grep/glob
- `minirun/tools/__init__.py` — registro automático na inicialização
- `config/mcp.yaml` — configuração de servidores MCP
- `minirun --tools` lista todas as tools registradas
