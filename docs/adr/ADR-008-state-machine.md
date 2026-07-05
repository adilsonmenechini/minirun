# ADR-008: Explicit Runtime State Machine

**Status:** ✅ Accepted (2026-07-05)

**Related ADRs:** [ADR-001: Single Deterministic Runtime](ADR-001-runtime.md), [ADR-007: Knowledge Store](ADR-007-knowledge-store.md)

---

## Context

O runtime descrito no ADR-001 originalmente executava um loop `while True` implícito:

```python
while True:
    context = build_context()
    response = provider.complete(context)
    if response.has_tool():
        policy.check(response.tool) → tool.execute()
        continue
    break
```

Esse loop funcionava, mas tinha limitações significativas:

1. **Não observável** — não era possível saber em que fase do pipeline a execução estava sem inspecionar logs não-estruturados
2. **Não auditável** — não havia registro estruturado de transições entre estados
3. **Difícil de debugar** — uma falha no meio do loop exigia rastrear manualmente o fluxo
4. **Sem garantia de sequência** — não havia validação de que BUILD_CONTEXT sempre precede CALL_PROVIDER
5. **Sem suporte a interrupção segura** — um `KeyboardInterrupt` podia deixar o runtime em estado inconsistente
6. **Acoplamento no CLI** — a lógica de estados estava espalhada entre `run()` e `run_chat()` sem uma abstração compartilhada

A necessidade de observar e auditar o runtime cresceu com a introdução do [EventJournal (ADR-005)](ADR-005-memory.md): queríamos que cada transição de estado gerasse um evento `state_transition` no journal, e que ferramentas como `/journal` ou `/events` pudessem mostrar o fluxo de execução.

---

## Decision

**Adotar uma State Machine explícita** com enum (`RuntimeState`), tabela de transições validada, e classe observável (`RuntimeStateMachine`).

### Estados

| Estado | Significado |
|--------|-------------|
| `IDLE` | Machine recém-criada, nenhuma transição ocorreu |
| `BUILD_CONTEXT` | Construindo contexto (memória, ferramentas, workspace) |
| `CALL_PROVIDER` | Enviando prompt para o LLM provider |
| `EXECUTE_TOOL` | Executando uma tool requisitada pelo LLM |
| `UPDATE_CONTEXT` | Atualizando contexto pós-resposta (extração de conhecimento, persistência) |
| `FINALIZE` | Terminal — sessão encerrada, sem transições válidas |

### Tabela de Transições

```
IDLE ──────────────────────────────→ BUILD_CONTEXT
                                      │
BUILD_CONTEXT ─────→ CALL_PROVIDER   │
                   ─→ FINALIZE ──────┘ (interrupt)

CALL_PROVIDER ───→ EXECUTE_TOOL
                ─→ UPDATE_CONTEXT
                ─→ FINALIZE (interrupt)

EXECUTE_TOOL ───→ UPDATE_CONTEXT
              ─→ FINALIZE (interrupt)

UPDATE_CONTEXT ──→ CALL_PROVIDER (loop — multi-turn chat)
               ─→ FINALIZE

FINALIZE ───────→ (terminal — nenhum estado válido)
```

Implementada como dicionário `_TRANSITIONS`:

```python
_TRANSITIONS: dict[RuntimeState, set[RuntimeState]] = {
    RuntimeState.IDLE:             {BUILD_CONTEXT},
    RuntimeState.BUILD_CONTEXT:    {CALL_PROVIDER, FINALIZE},
    RuntimeState.CALL_PROVIDER:    {EXECUTE_TOOL, UPDATE_CONTEXT, FINALIZE},
    RuntimeState.EXECUTE_TOOL:     {UPDATE_CONTEXT, FINALIZE},
    RuntimeState.UPDATE_CONTEXT:   {CALL_PROVIDER, FINALIZE},
    RuntimeState.FINALIZE:         set(),
}
```

### Tratamento de Interrupção

`FINALIZE` é permitido **de qualquer estado ativo** (BUILD_CONTEXT, CALL_PROVIDER, EXECUTE_TOOL, UPDATE_CONTEXT). Isso garante que:

- `KeyboardInterrupt` durante `provider.complete()` → `sm.transition(FINALIZE)` não quebra
- Erro durante `build_memory_context()` → é possível finalizar a sessão graciosamente
- Tool execution com falha → pode ir direto para FINALIZE sem UPDATE_CONTEXT

### Observabilidade

Cada transição:

1. **Valida** o movimento contra a tabela — `RuntimeError` se inválido
2. **Incrementa** o contador de transições (`transition_count`)
3. **Loga** via `log.debug("State transition #N: OLD → NEW")`
4. **Emite** evento `state_transition` no EventJournal via `safe_emit()` com payload:
   ```json
   {
     "from": "CALL_PROVIDER",
     "to": "UPDATE_CONTEXT",
     "count": 4
   }
   ```

### Exemplo de Uso no CLI

**Single-shot (`run()`):**

```
IDLE → BUILD_CONTEXT → CALL_PROVIDER → UPDATE_CONTEXT → FINALIZE
```

**Chat interativo (`run_chat()`):**

```
IDLE → BUILD_CONTEXT
         → CALL_PROVIDER → UPDATE_CONTEXT
         → CALL_PROVIDER → UPDATE_CONTEXT   (loop — N turns)
         → CALL_PROVIDER → UPDATE_CONTEXT
                              → FINALIZE    (terminal — Ctrl+C ou /exit)
```

### Integração com ToolExecutor

O `ToolExecutor` (extraído no runtime) também transita para `EXECUTE_TOOL` antes de executar uma tool:

```python
class ToolExecutor:
    async def execute(self, tool_name, params, session_id, state_machine=None):
        if state_machine is not None:
            state_machine.transition(RuntimeState.EXECUTE_TOOL)

        # permission check → registry lookup → execution → event
```

### Alternativas Consideradas

| Abordagem | Prós | Contras |
|-----------|------|---------|
| **State machine explícita** (escolhida) | Validável, testável (31 testes), auditável, resiliente a interrupts | Mais código que loop implícito |
| **Loop while True com log** | Simples, zero overhead | Sem validação, sem eventos, sem checkpoint |
| **Máquina de estados externa (STMP/transitions lib)** | Zero implementação | Dependência externa, sem controle fino de payload/eventos |
| **Estados como decorators/context managers** | Expressivo | Difícil de rastrear transições globalmente |

---

## Consequences

### Positivas

- **Pipeline observável** — cada transição gera um evento `state_transition` no EventJournal, visível via `/journal --type state_transition`
- **31 testes unitários** — 100% de cobertura da tabela de transições, incluindo paths de interrupção e loops multi-turn
- **Interrupção segura** — `KeyboardInterrupt` é tratado graciosamente: `FINALIZE` é válido de qualquer estado ativo
- **Separação de responsabilidades** — `RuntimeStateMachine` sabe apenas de estados/transições; os efeitos colaterais (build context, call provider) ficam no CLI
- **Reutilização** — `ToolExecutor` usa a mesma máquina de estados, transitando para `EXECUTE_TOOL`
- **Self-documenting** — o fluxo de execução pode ser lido diretamente no código: `sm.transition(BUILD_CONTEXT) → ... → sm.transition(FINALIZE)`
- **Preparado para ferramentas futuras** — estados como `EXECUTE_TOOL` já existem na tabela, mesmo que ainda não sejam usados por todos os fluxos

### Negativas

- **Mais código** — loop implícito era ~5 linhas; state machine adiciona ~80 linhas + 31 testes
- **Overhead de transição** — cada `transition()` faz validação, log, e emissão de evento (~0.1ms)
- **Transições são manuais** — o desenvolvedor precisa lembrar de chamar `sm.transition()` no ponto correto; esquecer resulta em `RuntimeError` (fail-fast) ou estado travado
- **Acoplamento ao EventJournal** — a máquina de estados depende de `safe_emit()` de `runtime/events.py`; se o journal não for inicializado, `safe_emit` é noop (graceful degradation)

## Compliance

| Componente | Módulo | Responsabilidade |
|-----------|--------|-----------------|
| **RuntimeState enum** | `minirun/runtime/state.py` | 6 estados: `IDLE`, `BUILD_CONTEXT`, `CALL_PROVIDER`, `EXECUTE_TOOL`, `UPDATE_CONTEXT`, `FINALIZE` |
| **RuntimeStateMachine** | `minirun/runtime/state.py` | `transition()`, `is_valid_transition()`, transições com log + evento |
| **Event type** | `minirun/memory/journal/journal.py` | `STATE_TRANSITION = "state_transition"` em `EVENT_TYPES` |
| **Exports** | `minirun/memory/__init__.py` | `STATE_TRANSITION` exportado |
| **Tool Executor** | `minirun/runtime/executor.py` | Transita para `EXECUTE_TOOL` antes de executar |
| **CLI single-shot** | `minirun/cli/main.py:run()` | `BUILD_CONTEXT → CALL_PROVIDER → UPDATE_CONTEXT → FINALIZE` |
| **CLI chat** | `minirun/cli/main.py:run_chat()` | `BUILD_CONTEXT → (loop: CALL_PROVIDER → UPDATE_CONTEXT) → FINALIZE` |
| **Testes** | `tests/runtime/test_state.py` | 31 testes — enum, transições, init, fluxos válidos, inválidos, eventos |
