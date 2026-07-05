# ADR-007: Knowledge Store

**Status:** ✅ Accepted (2026-07-05)

**Related ADRs:** [ADR-005: SQLite + Session Summaries](ADR-005-memory.md)

---

## Context

O runtime tinha memória episódica (session summaries via `memory/summaries.py`), mas não tinha **memória semântica** — fatos estruturados que persistem entre sessões e podem ser consultados independentemente do contexto de uma sessão específica.

O gap foi identificado no review de arquitetura (Gap 6 — Knowledge Store). A constituição já previa a hierarquia "Session → Summaries → Knowledge" e a tabela `knowledge` no schema, mas a implementação não existia.

Três decisões arquiteturais principais precisavam ser tomadas:

1. **Estratégia de extração** — como extrair fatos das respostas do LLM?
2. **Deduplicação** — como evitar duplicatas quando o mesmo fato é extraído múltiplas vezes?
3. **Persistência** — SQLite schema, WAL mode, indexação?

---

## Decision 1: Extração Heurística (Pattern-Based)

**Adotar extração baseada em regex patterns** em vez de uma chamada LLM separada.

### Alternativas Consideradas

| Abordagem | Latência | Precisão | Custo |
|-----------|----------|----------|-------|
| **LLM extraction** (call separado) | 2-5s | Alta | Alto (2x tokens por turno) |
| **Regex/pattern matching** | <10ms | Média | Zero |
| **Hybrid (patterns + classifier)** | 50-100ms | Alta | Mínimo (stdlib) |

### Rationale

- LLM extraction foi rejeitado por latência e custo — extrair fatos de cada resposta dobraria o custo de tokens
- Regex é deterministico, zero custo de inferência, e suficiente para padrões operacionais estruturados (incident IDs, dependências, runbooks)
- Hybrid approach foi escolhido: patterns v1 com possibilidade de adicionar heurísticas leves no futuro
- Extração é limitada a sessões `--chat` (não single-shot), conforme especificação

### Pattern Registry (v1)

```python
"incident":    (incident|case|ticket)[-#:]\s*\w+
"dependency":  (\w+)\s+(depends on|requires|uses)\s+(\w+)
"root_cause":  (caused by|due to|triggered by)\s+(.+)
"alert":       (alert|alarm|threshold)\s*(:|=|is|was)\s*(.+)
"runbook":     (runbook|doc|docs?)\s*(:|=|is|at)\s*(.+)
```

---

## Decision 2: Deduplicação por Content Hash (SHA-256)

**Adotar hash SHA-256 do conteúdo normalizado** para detectar e evitar duplicatas.

### Fluxo

```text
LLM Response
    ↓
KnowledgeExtractor.extract()
    ↓
Lista de KnowledgeFact (cada um com content_hash = SHA-256( normalized(content) ))
    ↓
KnowledgeStore.upsert(fact):
    content_hash existe? → UPDATE (incrementa version, atualiza updated_at)
    content_hash não existe? → INSERT (version=1)
```

### Normalização

Antes do hash, o conteúdo é normalizado:
- Lowercase
- Trim de whitespace
- Collapse de múltiplos espaços em um

### Conflict Resolution

- **V1**: Last-write-wins com contador de versão
- Não há merge automático ou arbitragem por confiança em v1
- O campo `confidence` (0.0–1.0) está no schema para uso futuro

### Alternativas Consideradas

- **Semantic similarity (embeddings)** — Rejeitado por YAGNI para ≤10k fatos. Exigiria modelo de embedding + dependência externa
- **Exact string match apenas** — Rejeitado porque o LLM pode reformular o mesmo fato de forma diferente entre sessões

---

## Decision 3: SQLite WAL Mode + Schema Desacoplado

**Adotar SQLite com WAL journal mode** em arquivo separado do índice de summaries.

### Schema

```sql
CREATE TABLE IF NOT EXISTS knowledge_facts (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    source_session_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT '[]',       -- JSON array
    content_hash TEXT NOT NULL UNIQUE,
    confidence REAL NOT NULL DEFAULT 1.0,
    version INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX idx_knowledge_content_hash ON knowledge_facts(content_hash);
CREATE INDEX idx_knowledge_tags ON knowledge_facts(tags);
CREATE INDEX idx_knowledge_created_at ON knowledge_facts(created_at DESC);
```

### Rationale

- **WAL mode**: Permite leitura concorrente durante extração (reads não bloqueiam writes)
- **Arquivo separado**: Evita acoplamento com o índice de summaries; cada sistema pode evoluir independentemente
- **Tags como JSON array**: Flexível para categorização sem schema rígido; filtrado via SQL LIKE com escape
- **content_hash UNIQUE**: Garantia de deduplicação em nível de banco de dados (além da lógica em código)

### Localização

- DB: `workspace/memory/knowledge/index.sqlite`
- Diretório criado automaticamente pelo `KnowledgeStore.__init__()`

---

## Consequences

### Positivas

- **Extração sem custo de inferência** — regex é ~10ms vs 2-5s de uma chamada LLM extra
- **Deduplicação determinística** — mesmo conteúdo, mesmo hash, independente de sessão ou perfil
- **Sem dependências externas** — tudo stdlib (sqlite3, hashlib, uuid, re, dataclasses)
- **Schema preparado para evolução** — campos `confidence`, `version`, `tags` permitem expansão sem migração
- **Separação clara de responsabilidades** — `KnowledgeStore` (persistência) ≠ `KnowledgeExtractor` (extração) ≠ `build_memory_context()` (injeção)

### Negativas

- **Regex não captura fatos implícitos** — apenas padrões explícitos e estruturados
- **Sem similaridade semântica** — fatos sobre o mesmo tópico com wording muito diferente não são deduplicados
- **Tags como JSON em TEXT** — filtragem via LIKE é funcional mas menos eficiente que uma tabela de tags normalizada (aceitável para ≤10k facts)
- **Sem expurgo automático** — fatos acumulam indefinidamente; TTL-based pruning é uma melhoria futura

## Compliance

- `minirun/memory/knowledge.py` — `KnowledgeFact` dataclass + `KnowledgeStore` (SQLite CRUD) + helpers
- `minirun/memory/extractor.py` — `KnowledgeExtractor` + `DEFAULT_PATTERNS`
- `minirun/memory/__init__.py` — exporta `KnowledgeStore`, `KnowledgeExtractor`, etc.
- `minirun/cli/main.py` — inicialização em `run_chat()` + extração pós-resposta + comandos `/knowledge`
- `minirun/runtime/harness.py` — `build_memory_context()` extendido com injeção de fatos
- `tests/memory/test_knowledge.py` — 38 testes (helpers, CRUD, extractor, edge cases)
