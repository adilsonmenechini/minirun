# ADR-001: Single Deterministic Runtime

**Status:** ✅ Accepted (2026-07-04)

---

## Context

O projeto começou como um "AI Agent" — a tentação de criar Agent, Subagent, Planner, Supervisor, Critic era grande. Frameworks como LangChain, CrewAI, e AutoGen popularizaram a abordagem multi-agente, onde múltiplos "agents" colaboram para resolver uma task.

Observamos, porém, que:
- A complexidade de coordenar múltiplos agents não se justifica para automação operacional (SRE)
- O debugging de sistemas multi-agente é significativamente mais difícil
- A latência adicional da coordenação entre agents não é aceitável para tasks SRE (incident response)
- A maioria das tasks operacionais é sequencial e determinística — não requer "deliberação" entre agents

## Decision

**Adotar um runtime único e determinístico** em vez de um sistema multi-agente.

O runtime executa um loop único:

```python
while True:
    context = build_context()
    response = provider.complete(context)
    if response.has_tool():
        policy.check(response.tool) → tool.execute()
        continue
    break
```

Não existe:
- `Agent`, `Subagent`, `Planner`, `Supervisor`, `Critic`
- Orquestração entre múltiplos LLMs
- Roteamento dinâmico de tasks entre agents

Toda a especialização vem dos **profiles** (configuração estática), não de agents executando concorrentemente.

## Consequences

**Positivas:**
- Complexidade drasticamente reduzida (runtime cabe em um arquivo: `runtime/harness.py`)
- Execução previsível e auditável — cada passo é um tool_call explícito
- Latência mínima — sem overhead de coordenação entre agents
- Debugging simples — log linear das tool calls
- Fácil de testar — sem estado compartilhado entre agents

**Negativas:**
- Não é possível executar múltiplas tasks em paralelo dentro de uma mesma sessão
- Tasks que exigiriam "pesquisa em paralelo" (ex: consultar 3 fontes simultaneamente) precisam ser feitas sequencialmente ou delegadas a tools MCP
- Não há "debate" ou "revisão" entre múltiplas perspectivas — a resposta é de um único LLM

## Compliance

- `minirun/runtime/harness.py` contém todo o loop de execução
- `minirun/cli/main.py` implementa o entry point único (single-shot ou `--chat`)
- Não existem classes Agent, Subagent, Planner, Supervisor, Critic em nenhum lugar do código
- Toda execução é linear: CLI → bootstrap → provider → tools → finalize
