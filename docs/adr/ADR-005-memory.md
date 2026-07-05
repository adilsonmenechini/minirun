# ADR-005: SQLite + Session Summaries

**Status:** ✅ Accepted (2026-07-04)

---

## Context

O runtime precisa de memória entre sessões — o usuário deve poder referenciar incidentes passados e o LLM deve ter contexto do que aconteceu anteriormente. As alternativas consideradas:

1. **Vector DB (Chroma, Qdrant, Pinecone)**: embeddings + similarity search para recuperar mensagens relevantes
2. **SQLite + summaries**: LLM gera um resumo bullet ao final de cada sessão, armazenado em SQLite com busca por keyword
3. **Full message history**: armazenar todas as mensagens em JSON e pesquisar por string matching
4. **Nenhuma memória**: cada sessão começa do zero

Vector DB foi rejeitado porque:
- Adiciona dependência externa significativa
- Requer modelo de embedding + pipeline de chunking
- Aumenta a complexidade de deploy
- O review do projeto explicitamente diz "SQLite > Infrastructure"
- Para o caso de uso SRE, keyword search nos prompts das sessões é suficiente — não precisamos de similarity search em mensagens individuais

## Decision

**Adotar SQLite + session summaries gerados por LLM** como mecanismo de memória entre sessões.

Fluxo:
```
Session ends
    ↓
LLM gera bullet summary da sessão
    ↓
Summary salvo como .md em workspace/memory/sessions/summaries/{id}.md
    ↓
Metadados (session_id, prompt, created_at) indexados em SQLite
    ↓
Próxima sessão: build_memory_context() consulta SQLite por LIKE match
    ↓
Summaries relevantes são injetados como mensagem system no início da conversa
```

Tabela SQLite:
```sql
CREATE TABLE summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    prompt TEXT NOT NULL,
    created_at TEXT NOT NULL
);
```

## Consequences

**Positivas:**
- Zero infraestrutura externa — apenas SQLite (já incluso no Python stdlib)
- Summaries são legíveis por humanos — arquivos .md em disco
- Busca por keyword é simples e previsível (SQL LIKE)
- LLM faz o trabalho pesado de sumarização — não precisamos de NLP ou embeddings
- Fácil de debugar — abrir o arquivo .md e ler o summary

**Negativas:**
- Keyword search é menos preciso que vector search — termos diferentes para o mesmo conceito não são匹配dos
- Apenas o prompt da sessão é indexado, não o conteúdo completo — sessions com prompts genéricos podem não ser encontradas
- Summaries dependem da qualidade do LLM — um summary mal gerado resulta em memória pobre
- Sem suporte a "knowledge" persistente (fatos extraídos que transcendem sessions individuais)

## Compliance

- `minirun/memory/summaries.py` — `KnowledgeIndex` (SQLite) + `summarize_session()` + `search_summaries()`
- `minirun/runtime/harness.py` — `build_memory_context()` consulta summaries e retorna contexto formatado
- `minirun/runtime/harness.py` — `finalize_session()` coordena a sumarização ao final de cada sessão
- Summaries salvos em `workspace/memory/sessions/summaries/{session_id}.md`
- Índice SQLite em `workspace/memory/sessions/index.sqlite`
