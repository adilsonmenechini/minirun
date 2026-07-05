# ADR-006: Default-Deny Security Policy

**Status:** ✅ Accepted (2026-07-04)

---

## Context

O runtime executa tools que podem:
- Ler e escrever arquivos no sistema (`filesystem.read`, `filesystem.write`)
- Fazer requisições HTTP para domínios arbitrários (`http.get`, `http.post`)
- Executar comandos shell (`shell.exec`)
- Chamar APIs externas via MCP

Sem um mecanismo de segurança, o LLM poderia instruir o runtime a executar operações destrutivas ou acessar dados sensíveis. As alternativas consideradas:

1. **Sem política**: qualquer tool pode ser chamada a qualquer momento — confiança total no LLM
2. **Allowlist explícita (default-deny)**: apenas tools explicitamente listadas podem ser executadas
3. **Denylist**: todas as tools são permitidas exceto as explicitamente bloqueadas
4. **Path/domain restrictions**: além da allowlist, verificar paths e domínios dos parâmetros

## Decision

**Adotar default-deny com allowlist + path/domain restrictions.** Toda tool invocation passa pelo Policy Engine antes da execução.

Ordem de avaliação:
```
1. tool_name em denied_tools? → DENY
2. tool_name em allowed_tools? → DENY se não estiver
3. path no params? → check allowed_paths (prefix matching)
4. url no params? → extract domain → check allowed_domains (wildcard matching)
5. Tudo ok → ALLOW
```

Política configurada em `config/security.yaml`:
```yaml
policy:
  allowed_tools:    [filesystem.read, http.get, ...]
  denied_tools:     [filesystem.write, shell.exec]
  allowed_paths:    [workspace/, /tmp/minirun/]
  allowed_domains:  [*.datadoghq.com, api.github.com]
```

## Consequences

**Positivas:**
- Segurança por configuração — não por código
- Default-deny significa que esqueceu de listar uma tool? Ela é negada (safe default)
- Path e domain restrictions limitam o dano mesmo que uma tool seja permitida
- Logging estruturado de toda denial (tool, reason, params) — audit trail completo
- `--allow-all` permite bypass para desenvolvimento sem modificar a política

**Negativas:**
- Configuração inicial requer manutenção — toda nova tool precisa ser adicionada à allowlist
- Path matching pode ser impreciso — symlinks e mounts podem bypassar prefix matching
- Domain matching com wildcard pode ser muito permissivo (`*.datadoghq.com` permite qualquer subdomínio)
- A política é estática (carregada na inicialização) — mudanças requerem restart

## Compliance

- `minirun/security/policy.py` — `PolicyEngine` implementa `evaluate()`, `check_tool()`, `check_path()`, `check_domain()`
- `config/security.yaml` — arquivo de configuração da política
- `minirun/runtime/harness.py` — `bootstrap()` carrega o `PolicyEngine`; `check_tool_permission()` é o entry point
- Toda tool execution em `tools/http.py` e `tools/filesystem.py` passa por `check_tool_permission()`
- `minirun/cli/main.py` — `--allow-all` flag para bypass em desenvolvimento
- `minirun/security/__init__.py` — exporta `PolicyDecision` (ALLOW, DENY, DENY_WITH_REASON) e `SecurityPolicy` dataclass
