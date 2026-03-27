# 05 — LLM Provider Integration

## Provider Abstraction Architecture

```
domain/ports.py
    │
    ├── IProviderAdapter (abstract interface)
    │       ├── get_capabilities() → ProviderCapabilities
    │       ├── test_connection() → ConnectionTestResult
    │       ├── discover_models() → list[ModelInfo]
    │       ├── chat(messages, config) → ProviderResponse
    │       ├── chat_structured(messages, schema, config) → ProviderResponse
    │       └── get_name() → str
    │
infrastructure/providers/
    ├── base.py
    │       ├── ProviderCapabilities (dataclass)
    │       ├── ModelInfo (dataclass)
    │       ├── ConnectionTestResult (dataclass)
    │       ├── ProviderResponse (dataclass)
    │       └── ProviderConfig helpers
    │
    ├── openai_adapter.py
    │       └── OpenAIProviderAdapter(IProviderAdapter)
    │
    └── anthropic_adapter.py
            └── AnthropicProviderAdapter(IProviderAdapter)
```

## IProviderAdapter Interface

```python
class IProviderAdapter(ABC):
    """Port for LLM provider integration."""

    @abstractmethod
    def get_name(self) -> str: ...

    @abstractmethod
    def get_capabilities(self) -> ProviderCapabilities: ...

    @abstractmethod
    async def test_connection(self, api_key: str) -> ConnectionTestResult: ...

    @abstractmethod
    async def discover_models(self, api_key: str) -> list[ModelInfo]: ...

    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, str]],
        config: ChatConfig,
    ) -> ProviderResponse: ...

    @abstractmethod
    async def chat_structured(
        self,
        messages: list[dict[str, str]],
        response_schema: type[BaseModel],
        config: ChatConfig,
    ) -> ProviderResponse: ...
```

## ProviderCapabilities

```python
@dataclass
class ProviderCapabilities:
    supports_model_discovery: bool = False
    supports_reasoning_control: bool = False
    supports_structured_output: bool = False
    supports_tool_use: bool = False
    supports_batch: bool = False
    supports_streaming: bool = False
    supports_temperature: bool = True
    max_context_window: int | None = None
    reasoning_control_name: str = ""     # e.g., "thinking" for Anthropic
    reasoning_levels: list[str] = field(default_factory=list)  # e.g., ["low", "medium", "high"]
```

## Capability Matrix

| Capability | OpenAI | Anthropic |
|-----------|--------|-----------|
| Model discovery | Yes (GET /v1/models) | Yes (GET /v1/models) |
| Reasoning control | No (unless o-series) | Yes (extended thinking: budget_tokens) |
| Structured output (JSON mode) | Yes (response_format) | Yes (tool_use trick or prefill) |
| Tool use | Yes | Yes |
| Batch | Yes (Batch API) | Yes (Message Batches) |
| Streaming | Yes | Yes |
| Temperature | Yes | Yes |

## OpenAI Adapter Implementation

```python
class OpenAIProviderAdapter(IProviderAdapter):
    """Adapter for OpenAI API using httpx."""

    BASE_URL = "https://api.openai.com/v1"

    def get_name(self) -> str:
        return "openai"

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_model_discovery=True,
            supports_reasoning_control=False,  # Simplified; o-series handling can be added
            supports_structured_output=True,
            supports_tool_use=True,
            supports_batch=True,
            supports_streaming=True,
            supports_temperature=True,
        )

    async def test_connection(self, api_key: str) -> ConnectionTestResult:
        """GET /v1/models with provided key, check for 200."""

    async def discover_models(self, api_key: str) -> list[ModelInfo]:
        """GET /v1/models, filter to chat-capable models, return sorted list."""

    async def chat(self, messages, config) -> ProviderResponse:
        """POST /v1/chat/completions with httpx."""

    async def chat_structured(self, messages, response_schema, config) -> ProviderResponse:
        """POST /v1/chat/completions with response_format=json_schema."""
```

### Key Implementation Details — OpenAI
- Use `httpx.AsyncClient` with configurable timeout
- Model discovery: `GET /v1/models`, filter by `id` containing "gpt" or known chat prefixes
- Structured output: Use `response_format: { type: "json_schema", json_schema: {...} }`
- Retry: `tenacity` with exponential backoff on 429, 500, 502, 503
- Headers: `Authorization: Bearer {api_key}`

## Anthropic Adapter Implementation

```python
class AnthropicProviderAdapter(IProviderAdapter):
    """Adapter for Anthropic Messages API using httpx."""

    BASE_URL = "https://api.anthropic.com/v1"

    def get_name(self) -> str:
        return "anthropic"

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_model_discovery=True,
            supports_reasoning_control=True,
            supports_structured_output=True,
            supports_tool_use=True,
            supports_batch=True,
            supports_streaming=True,
            supports_temperature=True,
            reasoning_control_name="thinking",
            reasoning_levels=["low", "medium", "high"],
        )

    async def test_connection(self, api_key: str) -> ConnectionTestResult:
        """POST /v1/messages with minimal prompt, check for 200."""

    async def discover_models(self, api_key: str) -> list[ModelInfo]:
        """GET /v1/models, return available models."""

    async def chat(self, messages, config) -> ProviderResponse:
        """POST /v1/messages with httpx."""

    async def chat_structured(self, messages, response_schema, config) -> ProviderResponse:
        """POST /v1/messages with tool_use to enforce schema, or prefill technique."""
```

### Key Implementation Details — Anthropic
- Headers: `x-api-key: {api_key}`, `anthropic-version: 2023-06-01`
- Model discovery: `GET /v1/models`
- Reasoning control: Include `thinking` block with `budget_tokens` in request
- Structured output: Use tool_use with a single tool whose input_schema matches desired output
- Retry: same tenacity pattern, respecting `retry-after` header on 429

## ChatConfig

```python
@dataclass
class ChatConfig:
    """Configuration for a single chat request."""
    api_key: str
    model: str
    temperature: float | None = None
    max_tokens: int = 4096
    timeout_seconds: int = 60
    reasoning_effort: str | None = None  # For Anthropic thinking
    response_format: str | None = None   # "json" for OpenAI
    system_prompt: str = ""
```

## ProviderResponse

```python
@dataclass
class ProviderResponse:
    content: str
    model: str
    provider: str
    usage: dict[str, int] = field(default_factory=dict)  # {"input_tokens": ..., "output_tokens": ...}
    raw_response: dict = field(default_factory=dict)
    latency_ms: float = 0.0
    success: bool = True
    error_message: str = ""
```

## ModelInfo

```python
@dataclass
class ModelInfo:
    id: str              # e.g., "gpt-4o", "claude-sonnet-4-20250514"
    name: str            # Display name
    provider: str
    context_window: int | None = None
    supports_vision: bool = False
    supports_tools: bool = False
    created_at: datetime | None = None
```

## Secret Storage

```python
# infrastructure/secrets/keyring_store.py

class KeyringSecretStore(ISecretStore):
    """Stores API keys in OS-native keyring (Windows Credential Locker, macOS Keychain, etc.)."""
    SERVICE_NAME = "bom-workbench"

    async def store_key(self, provider: str, api_key: str) -> None:
        """Store API key in keyring."""
        keyring.set_password(self.SERVICE_NAME, provider, api_key)

    async def get_key(self, provider: str) -> str | None:
        """Retrieve API key from keyring."""
        return keyring.get_password(self.SERVICE_NAME, provider)

    async def delete_key(self, provider: str) -> None:
        """Remove API key from keyring."""
        keyring.delete_password(self.SERVICE_NAME, provider)
```

## Provider Registration

At application startup (`app.py`), providers are registered:

```python
provider_registry: dict[str, IProviderAdapter] = {
    "openai": OpenAIProviderAdapter(),
    "anthropic": AnthropicProviderAdapter(),
}
```

The UI reads `provider_registry` to populate the Providers page. Adding a new provider = implementing `IProviderAdapter` + adding one line to the registry.
