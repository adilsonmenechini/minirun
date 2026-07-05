# ADR-007: Knowledge Store

**Status:** ✅ Accepted (2026-07-05)

**Related ADRs:** [ADR-005: SQLite + Session Summaries](ADR-005-memory.md), [ADR-001: Single Deterministic Runtime](ADR-001-runtime.md)

---

## Context

O runtime tinha memória episódica (session summaries via `memory/journal/`), mas não tinha **memória semântica** — fatos estruturados que persistem entre sessões e podem ser consultados independentemente do contexto de uma sessão específica.

O gap foi identificado no review de arquitetura (Gap 6 — Knowledge Store). A constituição já previa a hierarquia "Session → Summaries → Knowledge" e a tabela `knowledge` no schema, mas a implementação não existia.

Quatro decisões arquiteturais principais precisavam ser tomadas:

1. **Estratégia de extração** — como extrair fatos das respostas do LLM?
2. **Deduplicação** — como evitar duplicatas quando o mesmo fato é extraído múltiplas vezes?
3. **Persistência** — SQLite schema, WAL mode, indexação?
4. **Orquestração pós-sessão** — como coordenar extração em massa ao final da sessão?

---

## Decision 1: Extração Heurística (Pattern-Based) com Config YAML

**Adotar extração baseada em regex patterns** com configuração externa via YAML.

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
- Extração ocorre tanto em sessões `--chat` (inline, a cada resposta) quanto no build pós-sessão

### Pattern Registry (v1)

**Built-in patterns** (sempre ativos):

| Pattern | Regex | Exemplo |
|---------|-------|--------|
| `incident` | `(incident|case|ticket)[-#:\s]*(\w+)` | `incident-12345` |
| `dependency` | `(\w+)\s+(depends on|requires|uses)\s+(\w+)` | `auth depends on redis` |
| `root_cause` | `(caused by|due to|triggered by)\s+(.+)` | `caused by config typo` |
| `alert` | `(alert|alarm|threshold)\s*(:|=|is|was)\s*(.+)` | `alert: high CPU` |
| `runbook` | `(runbook|doc|docs?)\s*(:|=|is|at)\s*(.+)` | `runbook: wiki/incident-response` |

### Configuração via YAML

Patterns podem ser **estendidos ou sobrescritos** via `config/knowledge.yaml`:

```yaml
patterns:
  incident: "(INC|ticket)[-:#\\s]*(\\w+)"     # override built-in
  deployment: "(deploy|rollback|release)\\s*(:|=|to)\\s*(.+)"  # custom
```

- Custom patterns **mergem** com built-ins: mesmo nome → override; nome novo → adicionado
- YAML inválido ou ausente → apenas built-ins (sem erro)
- Regex inválidos no YAML → ignorados (default mantido)

### Heurísticas de Pós-Processamento

- **Mínimo 10 caracteres** por match (`_MIN_CONTENT_LENGTH = 10`)
- **Deduplicação intra-resposta**: matches com mesmo texto normalizado são ignorados
- Tags de categoria (ex: `["datadog", "incident"]`) são atribuídas automaticamente

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

## Decision 3: SQLite WAL Mode + Schema Desacoplado + TTL-based Pruning

**Adotar SQLite com WAL journal mode** em arquivo separado do índice de summaries, com expurgo automático por TTL.

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
    version INTEGER NOT NULL DEFAULT 1,
    expires_at TEXT                       -- ISO datetime, NULL = never expires
);

CREATE INDEX idx_knowledge_content_hash ON knowledge_facts(content_hash);
CREATE INDEX idx_knowledge_tags ON knowledge_facts(tags);
CREATE INDEX idx_knowledge_created_at ON knowledge_facts(created_at DESC);
```

### Evolução do Schema

A coluna `expires_at` foi adicionada posteriormente via `ALTER TABLE` com `try/except OperationalError` — migração segura em DBs existentes. O schema atual é o resultado final.

### TTL e Auto-Prune

- `KnowledgeFact.new()` aceita `ttl_days` (default: **90 dias**). `ttl_days=0` = sem expiração
- `KnowledgeStore.__init__(auto_prune=True)` executa `prune()` na inicialização:
  ```python
  def prune(self) -> int:
      now = datetime.now(UTC).isoformat()
      DELETE FROM knowledge_facts
      WHERE expires_at IS NOT NULL AND expires_at < ?
      -- retorna count de deletados
  ```
- Prune também é acionável via `/knowledge prune` no chat

### Rationale

- **WAL mode**: Permite leitura concorrente durante extração (reads não bloqueiam writes)
- **Arquivo separado**: Evita acoplamento com o índice de summaries; cada sistema pode evoluir independentemente
- **Tags como JSON array**: Flexível para categorização sem schema rígido; filtrado via SQL LIKE com escape
- **content_hash UNIQUE**: Garantia de deduplicação em nível de banco de dados (além da lógica em código)
- **TTL-based pruning**: Fatos operacionais perdem relevância com o tempo; prune automático evita crescimento infinito sem intervenção manual

### Localização

- DB: `workspace/memory/knowledge/index.sqlite`
- Diretório criado automaticamente pelo `KnowledgeStore.__init__()`

---

## Decision 4: Knowledge Builder — Orquestração Pós-Sessão

**Adotar uma camada de orquestração** (`memory/builder.py`) que coordena extração em massa ao final de cada sessão.

### Problema

A extração inline (a cada resposta do LLM) capturava fatos durante a sessão, mas:
- Sessões single-shot (`run()`) não tinham extração alguma
- A extração inline só processava a última resposta, não o histórico completo
- Não havia consistência entre sessões `--chat` e single-shot

### Solução

`build_knowledge()` processa **toda a conversa** (mensagens do usuário + respostas do assistente) após `finalize_session()`:

```python
def build_knowledge(
    messages: list[dict[str, str]] | list[Any],
    source_session_id: str,
    tags: list[str] | None = None,
    store: KnowledgeStore | None = None,
    extractor: KnowledgeExtractor | None = None,
) -> dict[str, int]:
```

### Fluxo Pós-Sessão

```
Session ends
    ↓
finalize_session()  →  LLM gera summary → salva em SQLite + .md
    ↓
build_knowledge()   →  para cada mensagem na conversa:
                           extractor.extract(content)
                           store.upsert(fact)
    ↓
Retorna {extracted: N, skipped: M}
```

### Características

- **Suporta dicts e objetos**: trata `msg["content"]` e `msg.content` igualmente
- **Lazy initialization**: se `store`/`extractor` não forem fornecidos, cria instâncias default
- **Resiliente**: chamada dentro de `try/except` no CLI — falha não quebra a finalização
- **Consistência**: mesma função chamada tanto em `run()` quanto em `run_chat()`

### Onde é chamada

| Fluxo | Local | Escopo |
|-------|-------|--------|
| `run()` (single-shot) | Após `finalize_session()` | Mensagens + 1 resposta |
| `run_chat()` (interativo) | Após `finalize_session()`, fora do `while True` | Todas as mensagens acumuladas + última resposta |

---

## Consequences

### Positivas

- **Extração sem custo de inferência** — regex é ~10ms vs 2-5s de uma chamada LLM extra
- **Deduplicação determinística** — mesmo conteúdo, mesmo hash, independente de sessão ou perfil
- **Sem dependências externas** — tudo stdlib (sqlite3, hashlib, uuid, re, dataclasses)
- **Schema preparado para evolução** — campos `confidence`, `version`, `tags`, `expires_at` permitem expansão sem migração
- **Separação clara de responsabilidades**:
  - `KnowledgeFact`/`KnowledgeStore` — persistência (CRUD)
  - `KnowledgeExtractor` — extração heurística
  - `build_knowledge()` — orquestração pós-sessão
  - `build_memory_context()` — injeção em contexto de sessão
- **TTL-based pruning automático** — fatos expiram após 90 dias sem intervenção manual
- **Configuração externa** — patterns podem ser estendidos via YAML sem modificar código

### Negativas

- **Regex não captura fatos implícitos** — apenas padrões explícitos e estruturados
- **Sem similaridade semântica** — fatos sobre o mesmo tópico com wording muito diferente não são deduplicados
- **Tags como JSON em TEXT** — filtragem via LIKE é funcional mas menos eficiente que uma tabela de tags normalizada (aceitável para ≤10k facts)
- **Extração pós-sessão duplica esforço** — fatos já extraídos inline são re-extraídos no `build_knowledge()`, mas deduplicação por hash impede duplicatas no store

## Compliance

| Componente | Módulo | Responsabilidade |
|-----------|--------|-----------------|
| **KnowledgeStore** | `minirun/memory/knowledge.py` | `KnowledgeFact` dataclass + SQLite CRUD + helpers (`normalize_content`, `compute_content_hash`) |
| **KnowledgeExtractor** | `minirun/memory/extractor.py` | `KnowledgeExtractor` + `DEFAULT_PATTERNS` + `load_knowledge_patterns()` |
| **Knowledge Builder** | `minirun/memory/builder.py` | `build_knowledge()` — orquestração pós-sessão |
| **Public API** | `minirun/memory/__init__.py` | Exporta todos os símbolos públicos |
| **CLI integração** | `minirun/cli/main.py` | `build_knowledge()` em `run()` e `run_chat()` + `KnowledgeStore`/`KnowledgeExtractor` |
| **Comandos /knowledge** | `minirun/cli/knowledge_commands.py` | `dispatch_knowledge_command()` — list, search, delete, prune |
| **Injeção em contexto** | `minirun/runtime/context.py` | `build_memory_context()` consulta KnowledgeStore + summaries |
| **Event journal** | `minirun/runtime/events.py` | `emit_event()`, `safe_emit()` integrados com o loop |
| **Testes** | `tests/memory/test_knowledge.py` | Helpers, CRUD, extractor, edge cases |
