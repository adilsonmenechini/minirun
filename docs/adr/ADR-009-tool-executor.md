# ADR-009: Tool Executor — Separação de Execução e Registro

**Status:** ✅ Accepted (2026-07-05)

**Related ADRs:** [ADR-001: Single Deterministic Runtime](ADR-001-runtime.md), [ADR-006: Security & Policy](ADR-006-security.md), [ADR-008: Explicit Runtime State Machine](ADR-008-state-machine.md)

---

## Context

O `ToolRegistry` original (`tools/registry.py`) acumulava duas responsabilidades distintas:

1. **Catálogo**: registrar, listar e consultar tools disponíveis
2. **Executor**: executar tools com verificações de permissão, emissão de eventos e transições de estado

Esse acoplamento causava problemas:

- `ToolRegistry` importava `PolicyDecision`, `ToolResult`, e dependia do `PolicyEngine` — conhecimento de segurança e execução
- O método `execute()` no registry não era `async`, limitando ferramentas futuras que exigissem I/O assíncrono
- Não havia emissão de eventos journal — uma tool executada silenciosamente não aparecia no EventJournal
- A transição de estado `EXECUTE_TOOL` da [ADR-008](ADR-008-state-machine.md) precisava ser chamada manualmente por quem usasse o registry, sem garantia de consistência
- O código de verificação de permissão estava espalhado entre `harness.py` (que define `check_tool_permission`) e `registry.py`

---

## Decision

**Extrair a responsabilidade de execução do `ToolRegistry` para um novo `ToolExecutor`** em `runtime/executor.py`, mantendo o `ToolRegistry` focado apenas em catálogo.

### Separação de Responsabilidades

| Camada | Módulo | Responsabilidade |
|--------|--------|-----------------|
| **Registry** | `tools/registry.py` | `register()`, `get_tool()`, `list_tools()` — apenas catálogo |
| **Executor** | `runtime/executor.py` | Policy check, state machine, eventos, execução |

### Antes (acoplado)

```
ToolRegistry
  ├─ register(name, fn)        ← OK (catálogo)
  ├─ get_tool(name) → dict      ← OK (catálogo)
  ├─ list_tools() → list        ← OK (catálogo)
  └─ execute(name, params)     ← PROBLEMA (execução + segurança)
       ├─ lookup tool
       ├─ permission check (PolicyEngine)
       └─ call execute_fn
```

### Depois (separado)

```
ToolRegistry                         ToolExecutor
  ├─ register(name, fn)                ├─ 1. sm.transition(EXECUTE_TOOL)
  ├─ get_tool(name) → dict             ├─ 2. check_tool_permission()
  └─ list_tools() → list               ├─ 3. registry.get_tool(name)
                                         ├─ 4. execute_fn(params)
                                         └─ 5. emit_tool_executed()
```

### Fluxo do `ToolExecutor.execute()`

```python
async def execute(self, tool_name, params=None, session_id=None, state_machine=None):
    # 1. State machine transition
    if state_machine is not None:
        state_machine.transition(RuntimeState.EXECUTE_TOOL)

    # 2. Permission check
    decision = check_tool_permission(tool_name, params, session_id)
    if decision != PolicyDecision.ALLOW:
        return {"success": False, "error": f"Policy denied: {decision.value}"}

    # 3. Registry lookup
    tool = self._registry.get_tool(tool_name)
    if tool is None:
        return {"success": False, "error": f"Unknown tool: {tool_name}"}

    # 4. Execute
    try:
        result = execute_fn(tool_name, params or {}, tool)
    except Exception as exc:
        return {"success": False, "error": str(exc)}

    # 5. Event journaling
    emit_tool_executed(tool_name, result, session_id)
    return result
```

### Tratamento de Erros

Cada etapa do pipeline tem tratamento específico:

| Etapa | Falha | Retorno |
|-------|-------|---------|
| Permission check | `PolicyDecision.DENY` | `{"success": False, "error": "Policy denied: ..."}` |
| Registry lookup | Tool não encontrada | `{"success": False, "error": "Unknown tool: ..."}` |
| Execution | Exceção na função | `{"success": False, "error": "<exception message>"}` |
| Event emission | Falha no journal | Log warning apenas (não quebra o resultado) |

### Por que `async`?

O método `execute()` é `async` mesmo que as tool functions atuais sejam síncronas. Isso é **preparação para o futuro**:

- Tools MCP já são chamadas via `session.call_tool()` que é `async`
- Tools que fazem I/O (HTTP, banco de dados) podem se beneficiar de execução assíncrona
- A assinatura `async` já existe desde a v1, evitando mudança breaking futura
- Chamar funções síncronas de dentro de um método `async` é válido em Python

### Onde o Executor é usado

Atualmente o `ToolExecutor` está definido e testado, mas a integração no loop principal (`run()` / `run_chat()`) será feita quando o pipeline de tool calling do LLM for integrado. O executor já é funcional e pode ser usado por código que chame tools diretamente.

### Alternativas Consideradas

| Abordagem | Prós | Contras |
|-----------|------|---------|
| **Executor separado** (escolhida) | SRP, testável, preparado para async | Mais uma classe, mais um arquivo |
| **Manter tudo no Registry** | Simples, zero refactoring | Acoplamento, difícil de testar isoladamente |
| **ToolRunner como função avulsa** | Sem classe extra | Sem estado, sem injeção de dependência |
| **Decorator de execução** | Expressivo | Complexidade de rastreamento, difícil de mockar |

---

## Consequences

### Positivas

- **Separação clara de responsabilidades** — `ToolRegistry` é puro catálogo (~60 linhas); `ToolExecutor` cuida de execução, segurança e observabilidade
- **Pipeline explícito** — as 5 etapas são visíveis e testáveis individualmente
- **Preparado para MCP** — `async` permite integração futura com `MCPClientManager.call_tool()` sem mudança de API
- **Event journal integrado** — toda execução emite `TOOL_EXECUTED` automaticamente
- **State machine integrada** — transição `EXECUTE_TOOL` é garantida pelo executor, não pelo caller
- **Tratamento de erro completo** — 4 pontos de falha com mensagens descritivas
- **Zero dependências externas** — tudo stdlib + módulos do projeto

### Negativas

- **Mais indireção** — para executar uma tool agora são necessárias duas classes (`ToolRegistry` + `ToolExecutor`) em vez de uma
- **Lazy import** — `check_tool_permission` é importado dentro do método `execute()` para evitar circular import com `harness.py`
- **`async` sem uso atual** — tool functions são síncronas; a assinatura `async` adiciona compatibilidade mas não traz benefício hoje
- **Executor não está integrado no loop principal** — o pipeline de tool calling do LLM ainda não usa `ToolExecutor`; ele existe como componente disponível

## Compliance

| Componente | Módulo | Responsabilidade |
|-----------|--------|-----------------|
| **ToolRegistry** | `minirun/tools/registry.py` | `register()`, `get_tool()`, `list_tools()` — catálogo puro |
| **ToolExecutor** | `minirun/runtime/executor.py` | `execute()` — policy check + state machine + eventos + execução |
| **ToolResult** | `minirun/tools/registry.py` + `minirun/runtime/executor.py` | Type alias `dict[str, Any]` (definido independentemente em cada módulo) |
| **check_tool_permission** | `minirun/runtime/harness.py` | Avalia política + emite `TOOL_REQUESTED`/`TOOL_DENIED` |
| **PolicyEngine** | `minirun/security/policy.py` | `evaluate(tool_name, params) → PolicyDecision` |
| **State Machine** | `minirun/runtime/state.py` | Transição `EXECUTE_TOOL` via `RuntimeStateMachine` |
| **Event emission** | `minirun/runtime/events.py` | `emit_tool_executed()` — trunca resultado em 200 chars |
| **Event types** | `minirun/memory/journal/journal.py` | `TOOL_EXECUTED`, `TOOL_REQUESTED`, `TOOL_DENIED` |
| **Tools registradas** | `minirun/tools/__init__.py` | `http.get`, `http.post`, `filesystem.*`, `shell.exec` |
