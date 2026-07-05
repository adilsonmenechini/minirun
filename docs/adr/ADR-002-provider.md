# ADR-002: Provider Abstraction

**Status:** ✅ Accepted (2026-07-04)

---

## Context

O runtime precisa suportar múltiplos provedores de LLM (OpenAI, Anthropic, e potencialmente Gemini, Azure, Ollama). Sem uma abstração limpa, o código do runtime ficaria acoplado a provedores específicos.

As alternativas consideradas foram:
1. **Acoplamento direto**: cada provedor com sua própria API e parser — runtime conhece provedores
2. **Interface abstrata única**: todos os provedores implementam `BaseProvider` — runtime conhece apenas a interface
3. **Adapter pattern**: provedores são wrapped em adapters que traduzem para um formato canônico

## Decision

**Adotar uma interface abstrata única (`BaseProvider`) no pacote `ports/`**, com implementações concretas em `adapters/`.

```python
class BaseProvider(abc.ABC):
    async def complete(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Response: ...
```

O runtime nunca importa OpenAI ou Anthropic diretamente. A resolução do provider é feita por nome em `providers/__init__.py`:

```python
PROVIDERS = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
}
```

## Consequences

**Positivas:**
- Troca de LLM sem alterar o runtime — basta `--provider anthropic`
- Novos provedores são adicionados criando um adapter que implementa `BaseProvider`
- Testabilidade: é possível criar um `MockProvider` para testes sem chamar APIs reais
- Isolamento: erros específicos de cada provedor são encapsulados nos adapters
- Classificação de erros consistente (`AuthenticationError`, `RateLimitError`, etc.)

**Negativas:**
- A interface precisa ser genérica o suficiente para suportar todos os provedores — features específicas de um provedor (ex: sonde de Anthropic) não são expostas
- Pequeno overhead de adaptação entre formatos de mensagem (ex: OpenAI usa `role: "developer"`, Anthropic usa `role: "assistant"`)

## Compliance

- `minirun/ports/provider.py` define `BaseProvider`, `Message`, `Response`, `Tool`, `ToolCall`, `Usage`
- `minirun/adapters/openai.py` e `minirun/adapters/anthropic.py` implementam `BaseProvider`
- `minirun/providers/__init__.py` mapeia nomes para classes
- `minirun/runtime/harness.py` usa `get_provider()` que retorna `BaseProvider` — nunca importa adapters diretamente
- `call_with_retry()` em `ports/provider.py` aplica exponential backoff para erros transientes
