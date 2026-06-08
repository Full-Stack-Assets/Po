"""
LLM Provider Abstraction Layer — llm_providers.py
Unified interface for OpenAI, Anthropic, Azure OpenAI, Google Gemini, Mistral, and Ollama.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import (Any, AsyncIterator, Dict, List, Optional, Tuple)
import json
import logging
import time

logger = logging.getLogger(__name__)


# ── Data Models ────────────────────────────────────────────────────────

class ProviderType(Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    AZURE_OPENAI = "azure_openai"
    GEMINI = "gemini"
    MISTRAL = "mistral"
    OLLAMA = "ollama"


@dataclass
class Message:
    """Universal message format used across all providers."""
    role: str                       # "system" | "user" | "assistant"
    content: str
    name: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = {"role": self.role, "content": self.content}
        if self.name:
            d["name"] = self.name
        return d


@dataclass
class TokenUsage:
    """Token usage and cost accounting for a single completion."""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    input_cost: float = 0.0
    output_cost: float = 0.0
    total_cost: float = 0.0
    currency: str = "USD"


@dataclass
class LLMResponse:
    """Unified response from any LLM provider."""
    content: str
    model: str
    provider: ProviderType
    usage: TokenUsage = field(default_factory=TokenUsage)
    finish_reason: str = ""
    latency_ms: float = 0.0
    raw_response: Optional[Dict[str, Any]] = None
    success: bool = True
    error: Optional[str] = None


@dataclass
class LLMChunk:
    """A single chunk from a streaming response."""
    content: str
    finish_reason: Optional[str] = None
    model: str = ""


@dataclass
class ModelInfo:
    """Metadata about an available model."""
    model_id: str
    provider: ProviderType
    display_name: str
    context_window: int = 128_000
    max_output_tokens: int = 4_096
    cost_per_1k_input: float = 0.0
    cost_per_1k_output: float = 0.0
    supports_streaming: bool = True
    supports_tools: bool = False
    supports_vision: bool = False
    capabilities: List[str] = field(default_factory=list)


@dataclass
class ProviderConfig:
    """Configuration for a single LLM provider."""
    provider_type: ProviderType
    api_key: str = ""
    base_url: Optional[str] = None
    organization: Optional[str] = None
    api_version: Optional[str] = None          # Azure
    deployment_name: Optional[str] = None       # Azure
    default_model: str = ""
    max_retries: int = 3
    timeout_seconds: int = 60
    enabled: bool = True
    extra: Dict[str, Any] = field(default_factory=dict)


# ── Cost Tables ────────────────────────────────────────────────────────

MODEL_COSTS: Dict[str, Tuple[float, float]] = {
    # OpenAI  (input $/1k, output $/1k)
    "gpt-4.1":               (0.002,  0.008),
    "gpt-4.1-mini":          (0.0004, 0.0016),
    "gpt-4.1-nano":          (0.0001, 0.0004),
    "gpt-4o":                (0.0025, 0.010),
    "gpt-4o-mini":           (0.00015,0.0006),
    "o3":                    (0.010,  0.040),
    "o3-mini":               (0.0011, 0.0044),
    "o4-mini":               (0.0011, 0.0044),
    # Anthropic
    "claude-sonnet-4-5":     (0.003,  0.015),
    "claude-opus-4":         (0.015,  0.075),
    "claude-haiku-3.5":      (0.0008, 0.004),
    # Google Gemini
    "gemini-2.5-pro":        (0.00125,0.010),
    "gemini-2.5-flash":      (0.00015,0.0006),
    "gemini-2.0-flash":      (0.0001, 0.0004),
    # Mistral
    "mistral-large-latest":  (0.002,  0.006),
    "mistral-small-latest":  (0.0001, 0.0003),
    "codestral-latest":      (0.0003, 0.0009),
    # DeepSeek (OpenAI-compatible)
    "deepseek-chat":         (0.00014, 0.00028),
    "deepseek-reasoner":     (0.00055, 0.00219),
    # Ollama (local — zero cost)
    "llama3":                (0.0, 0.0),
    "codellama":             (0.0, 0.0),
    "mixtral":               (0.0, 0.0),
    "deepseek-r1":           (0.0, 0.0),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> Tuple[float, float, float]:
    """Returns (input_cost, output_cost, total_cost) in USD."""
    costs = MODEL_COSTS.get(model, (0.0, 0.0))
    ic = (input_tokens / 1000) * costs[0]
    oc = (output_tokens / 1000) * costs[1]
    return ic, oc, ic + oc


# ── Abstract Base ──────────────────────────────────────────────────────

class BaseLLMProvider(ABC):
    """Abstract base class for all LLM providers."""

    def __init__(self, config: ProviderConfig):
        self.config = config
        self._client: Any = None

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the async client. Called once before first use."""
        ...

    @abstractmethod
    async def complete(
        self,
        messages: List[Message],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        stop: Optional[List[str]] = None,
        **kwargs
    ) -> LLMResponse:
        """Send a chat completion request and return the full response."""
        ...

    @abstractmethod
    async def stream_complete(
        self,
        messages: List[Message],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        stop: Optional[List[str]] = None,
        **kwargs
    ) -> AsyncIterator[LLMChunk]:
        """Stream a chat completion, yielding chunks as they arrive."""
        ...

    @abstractmethod
    def get_available_models(self) -> List[ModelInfo]:
        """Return metadata for all models available through this provider."""
        ...

    def estimate_cost(self, model: str, input_tokens: int,
                      output_tokens: int) -> TokenUsage:
        ic, oc, tc = estimate_cost(model, input_tokens, output_tokens)
        return TokenUsage(
            input_tokens=input_tokens, output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            input_cost=ic, output_cost=oc, total_cost=tc
        )

    async def close(self) -> None:
        """Cleanup resources."""
        pass


# ── OpenAI Provider ───────────────────────────────────────────────────

class OpenAIProvider(BaseLLMProvider):
    """Provider for OpenAI GPT models (gpt-4.1, gpt-4o, o3, o4-mini, etc.)."""

    async def initialize(self) -> None:
        from openai import AsyncOpenAI
        kwargs = dict(
            api_key=self.config.api_key,
            organization=self.config.organization,
            timeout=self.config.timeout_seconds,
            max_retries=self.config.max_retries,
        )
        if self.config.base_url:
            kwargs["base_url"] = self.config.base_url
        self._client = AsyncOpenAI(**kwargs)
        logger.info("OpenAI provider initialized")

    async def complete(self, messages: List[Message], model: Optional[str] = None,
                       temperature: float = 0.7, max_tokens: int = 4096,
                       stop: Optional[List[str]] = None, **kwargs) -> LLMResponse:
        model = model or self.config.default_model or "gpt-4.1-mini"
        start = time.time()
        try:
            resp = await self._client.chat.completions.create(
                model=model,
                messages=[m.to_dict() for m in messages],
                temperature=temperature,
                max_tokens=max_tokens,
                stop=stop,
                **kwargs,
            )
            latency = (time.time() - start) * 1000
            usage = self.estimate_cost(
                model,
                resp.usage.prompt_tokens,
                resp.usage.completion_tokens,
            )
            return LLMResponse(
                content=resp.choices[0].message.content or "",
                model=model,
                provider=ProviderType.OPENAI,
                usage=usage,
                finish_reason=resp.choices[0].finish_reason or "",
                latency_ms=latency,
            )
        except Exception as e:
            return LLMResponse(
                content="", model=model, provider=ProviderType.OPENAI,
                success=False, error=str(e),
                latency_ms=(time.time() - start) * 1000,
            )

    async def stream_complete(self, messages: List[Message],
                               model: Optional[str] = None,
                               temperature: float = 0.7,
                               max_tokens: int = 4096,
                               stop: Optional[List[str]] = None,
                               **kwargs) -> AsyncIterator[LLMChunk]:
        model = model or self.config.default_model or "gpt-4.1-mini"
        stream = await self._client.chat.completions.create(
            model=model,
            messages=[m.to_dict() for m in messages],
            temperature=temperature,
            max_tokens=max_tokens,
            stop=stop,
            stream=True,
            **kwargs,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta
            yield LLMChunk(
                content=delta.content or "",
                finish_reason=chunk.choices[0].finish_reason,
                model=model,
            )

    def get_available_models(self) -> List[ModelInfo]:
        return [
            ModelInfo("gpt-4.1", ProviderType.OPENAI, "GPT-4.1",
                      1_047_576, 32_768, 0.002, 0.008, True, True, True,
                      ["research","writing","code","analysis"]),
            ModelInfo("gpt-4.1-mini", ProviderType.OPENAI, "GPT-4.1 Mini",
                      1_047_576, 32_768, 0.0004, 0.0016, True, True, True,
                      ["research","writing","code","analysis"]),
            ModelInfo("gpt-4.1-nano", ProviderType.OPENAI, "GPT-4.1 Nano",
                      1_047_576, 32_768, 0.0001, 0.0004, True, True, False,
                      ["classification","routing","summarization"]),
            ModelInfo("o4-mini", ProviderType.OPENAI, "o4-mini",
                      200_000, 100_000, 0.0011, 0.0044, True, True, True,
                      ["reasoning","code","analysis","math"]),
        ]

    async def close(self) -> None:
        if self._client:
            await self._client.close()


# ── Anthropic Provider ────────────────────────────────────────────────

class AnthropicProvider(BaseLLMProvider):
    """Provider for Anthropic Claude models."""

    async def initialize(self) -> None:
        from anthropic import AsyncAnthropic
        kwargs = dict(
            api_key=self.config.api_key,
            timeout=self.config.timeout_seconds,
            max_retries=self.config.max_retries,
        )
        if self.config.base_url:
            kwargs["base_url"] = self.config.base_url
        self._client = AsyncAnthropic(**kwargs)
        logger.info("Anthropic provider initialized")

    async def complete(self, messages: List[Message], model: Optional[str] = None,
                       temperature: float = 0.7, max_tokens: int = 4096,
                       stop: Optional[List[str]] = None, **kwargs) -> LLMResponse:
        model = model or self.config.default_model or "claude-sonnet-4-5"
        start = time.time()

        # Anthropic uses a separate system parameter
        system_msg = ""
        chat_msgs = []
        for m in messages:
            if m.role == "system":
                system_msg += m.content + "\n"
            else:
                chat_msgs.append(m.to_dict())

        try:
            resp = await self._client.messages.create(
                model=model,
                system=system_msg.strip() or None,
                messages=chat_msgs,
                temperature=temperature,
                max_tokens=max_tokens,
                stop_sequences=stop,
                **kwargs,
            )
            latency = (time.time() - start) * 1000
            usage = self.estimate_cost(
                model, resp.usage.input_tokens, resp.usage.output_tokens
            )
            content = "".join(
                b.text for b in resp.content if hasattr(b, "text")
            )
            return LLMResponse(
                content=content, model=model,
                provider=ProviderType.ANTHROPIC,
                usage=usage,
                finish_reason=resp.stop_reason or "",
                latency_ms=latency,
            )
        except Exception as e:
            return LLMResponse(
                content="", model=model, provider=ProviderType.ANTHROPIC,
                success=False, error=str(e),
                latency_ms=(time.time() - start) * 1000,
            )

    async def stream_complete(self, messages: List[Message],
                               model: Optional[str] = None,
                               temperature: float = 0.7,
                               max_tokens: int = 4096,
                               stop: Optional[List[str]] = None,
                               **kwargs) -> AsyncIterator[LLMChunk]:
        model = model or self.config.default_model or "claude-sonnet-4-5"
        system_msg = ""
        chat_msgs = []
        for m in messages:
            if m.role == "system":
                system_msg += m.content + "\n"
            else:
                chat_msgs.append(m.to_dict())

        async with self._client.messages.stream(
            model=model,
            system=system_msg.strip() or None,
            messages=chat_msgs,
            temperature=temperature,
            max_tokens=max_tokens,
            stop_sequences=stop,
            **kwargs,
        ) as stream:
            async for text in stream.text_stream:
                yield LLMChunk(content=text, model=model)

    def get_available_models(self) -> List[ModelInfo]:
        return [
            ModelInfo("claude-sonnet-4-5", ProviderType.ANTHROPIC,
                      "Claude Sonnet 4.5", 200_000, 8_192, 0.003, 0.015,
                      True, True, True,
                      ["research","writing","code","analysis","reasoning"]),
            ModelInfo("claude-opus-4", ProviderType.ANTHROPIC,
                      "Claude Opus 4", 200_000, 32_000, 0.015, 0.075,
                      True, True, True,
                      ["deep_reasoning","code","writing","analysis"]),
            ModelInfo("claude-haiku-3.5", ProviderType.ANTHROPIC,
                      "Claude Haiku 3.5", 200_000, 8_192, 0.0008, 0.004,
                      True, True, True,
                      ["classification","summarization","routing"]),
        ]

    async def close(self) -> None:
        if self._client:
            await self._client.close()


# ── Azure OpenAI Provider ─────────────────────────────────────────────

class AzureOpenAIProvider(BaseLLMProvider):
    """Provider for Azure-hosted OpenAI models."""

    async def initialize(self) -> None:
        from openai import AsyncAzureOpenAI
        self._client = AsyncAzureOpenAI(
            api_key=self.config.api_key,
            azure_endpoint=self.config.base_url or "",
            api_version=self.config.api_version or "2025-03-01-preview",
            timeout=self.config.timeout_seconds,
            max_retries=self.config.max_retries,
        )
        logger.info("Azure OpenAI provider initialized")

    async def complete(self, messages: List[Message], model: Optional[str] = None,
                       temperature: float = 0.7, max_tokens: int = 4096,
                       stop: Optional[List[str]] = None, **kwargs) -> LLMResponse:
        deployment = model or self.config.deployment_name or self.config.default_model
        start = time.time()
        try:
            resp = await self._client.chat.completions.create(
                model=deployment,
                messages=[m.to_dict() for m in messages],
                temperature=temperature,
                max_tokens=max_tokens,
                stop=stop,
                **kwargs,
            )
            latency = (time.time() - start) * 1000
            usage = self.estimate_cost(
                deployment,
                resp.usage.prompt_tokens,
                resp.usage.completion_tokens,
            )
            return LLMResponse(
                content=resp.choices[0].message.content or "",
                model=deployment,
                provider=ProviderType.AZURE_OPENAI,
                usage=usage,
                finish_reason=resp.choices[0].finish_reason or "",
                latency_ms=latency,
            )
        except Exception as e:
            return LLMResponse(
                content="", model=deployment,
                provider=ProviderType.AZURE_OPENAI,
                success=False, error=str(e),
                latency_ms=(time.time() - start) * 1000,
            )

    async def stream_complete(self, messages: List[Message],
                               model: Optional[str] = None,
                               temperature: float = 0.7,
                               max_tokens: int = 4096,
                               stop: Optional[List[str]] = None,
                               **kwargs) -> AsyncIterator[LLMChunk]:
        deployment = model or self.config.deployment_name or self.config.default_model
        stream = await self._client.chat.completions.create(
            model=deployment,
            messages=[m.to_dict() for m in messages],
            temperature=temperature,
            max_tokens=max_tokens,
            stop=stop,
            stream=True,
            **kwargs,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta
            yield LLMChunk(
                content=delta.content or "",
                finish_reason=chunk.choices[0].finish_reason,
                model=deployment,
            )

    def get_available_models(self) -> List[ModelInfo]:
        name = self.config.deployment_name or "azure-deployment"
        return [
            ModelInfo(name, ProviderType.AZURE_OPENAI,
                      f"Azure: {name}", 128_000, 4_096, 0.002, 0.008,
                      True, True, True,
                      ["research","writing","code","analysis"]),
        ]

    async def close(self) -> None:
        if self._client:
            await self._client.close()


# ── Google Gemini Provider ─────────────────────────────────────────────

class GeminiProvider(BaseLLMProvider):
    """Provider for Google Gemini models via the OpenAI-compatible endpoint."""

    GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

    async def initialize(self) -> None:
        from openai import AsyncOpenAI
        self._client = AsyncOpenAI(
            api_key=self.config.api_key,
            base_url=self.config.base_url or self.GEMINI_BASE_URL,
            timeout=self.config.timeout_seconds,
            max_retries=self.config.max_retries,
        )
        logger.info("Gemini provider initialized (OpenAI-compatible)")

    async def complete(self, messages: List[Message], model: Optional[str] = None,
                       temperature: float = 0.7, max_tokens: int = 4096,
                       stop: Optional[List[str]] = None, **kwargs) -> LLMResponse:
        model = model or self.config.default_model or "gemini-2.5-flash"
        start = time.time()
        try:
            create_kwargs: Dict[str, Any] = dict(
                model=model,
                messages=[m.to_dict() for m in messages],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            if stop:
                create_kwargs["stop"] = stop
            resp = await self._client.chat.completions.create(
                **create_kwargs,
                **kwargs,
            )
            latency = (time.time() - start) * 1000
            usage = self.estimate_cost(
                model,
                resp.usage.prompt_tokens if resp.usage else 0,
                resp.usage.completion_tokens if resp.usage else 0,
            )
            return LLMResponse(
                content=resp.choices[0].message.content or "",
                model=model, provider=ProviderType.GEMINI,
                usage=usage,
                finish_reason=resp.choices[0].finish_reason or "",
                latency_ms=latency,
            )
        except Exception as e:
            return LLMResponse(
                content="", model=model, provider=ProviderType.GEMINI,
                success=False, error=str(e),
                latency_ms=(time.time() - start) * 1000,
            )

    async def stream_complete(self, messages: List[Message],
                               model: Optional[str] = None,
                               temperature: float = 0.7,
                               max_tokens: int = 4096,
                               stop: Optional[List[str]] = None,
                               **kwargs) -> AsyncIterator[LLMChunk]:
        model = model or self.config.default_model or "gemini-2.5-flash"
        create_kwargs: Dict[str, Any] = dict(
            model=model,
            messages=[m.to_dict() for m in messages],
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )
        if stop:
            create_kwargs["stop"] = stop
        stream = await self._client.chat.completions.create(
            **create_kwargs,
            **kwargs,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta
            yield LLMChunk(
                content=delta.content or "",
                finish_reason=chunk.choices[0].finish_reason,
                model=model,
            )

    def get_available_models(self) -> List[ModelInfo]:
        return [
            ModelInfo("gemini-2.5-pro", ProviderType.GEMINI, "Gemini 2.5 Pro",
                      1_048_576, 65_536, 0.00125, 0.010, True, True, True,
                      ["deep_reasoning","code","analysis","research"]),
            ModelInfo("gemini-2.5-flash", ProviderType.GEMINI, "Gemini 2.5 Flash",
                      1_048_576, 65_536, 0.00015, 0.0006, True, True, True,
                      ["writing","summarization","classification","code"]),
            ModelInfo("gemini-2.0-flash", ProviderType.GEMINI, "Gemini 2.0 Flash",
                      1_048_576, 8_192, 0.0001, 0.0004, True, True, True,
                      ["routing","classification","summarization"]),
        ]

    async def close(self) -> None:
        if self._client:
            await self._client.close()


# ── Mistral Provider ──────────────────────────────────────────────────

class MistralProvider(BaseLLMProvider):
    """Provider for Mistral AI models."""

    async def initialize(self) -> None:
        from mistralai import Mistral
        self._client = Mistral(
            api_key=self.config.api_key,
            timeout_ms=self.config.timeout_seconds * 1000,
            max_retries=self.config.max_retries,
        )
        logger.info("Mistral provider initialized")

    async def complete(self, messages: List[Message], model: Optional[str] = None,
                       temperature: float = 0.7, max_tokens: int = 4096,
                       stop: Optional[List[str]] = None, **kwargs) -> LLMResponse:
        model = model or self.config.default_model or "mistral-small-latest"
        start = time.time()
        try:
            resp = await self._client.chat.complete_async(
                model=model,
                messages=[m.to_dict() for m in messages],
                temperature=temperature,
                max_tokens=max_tokens,
                stop=stop,
            )
            latency = (time.time() - start) * 1000
            usage = self.estimate_cost(
                model,
                resp.usage.prompt_tokens,
                resp.usage.completion_tokens,
            )
            return LLMResponse(
                content=resp.choices[0].message.content or "",
                model=model, provider=ProviderType.MISTRAL,
                usage=usage,
                finish_reason=resp.choices[0].finish_reason or "",
                latency_ms=latency,
            )
        except Exception as e:
            return LLMResponse(
                content="", model=model, provider=ProviderType.MISTRAL,
                success=False, error=str(e),
                latency_ms=(time.time() - start) * 1000,
            )

    async def stream_complete(self, messages: List[Message],
                               model: Optional[str] = None,
                               temperature: float = 0.7,
                               max_tokens: int = 4096,
                               stop: Optional[List[str]] = None,
                               **kwargs) -> AsyncIterator[LLMChunk]:
        model = model or self.config.default_model or "mistral-small-latest"
        stream = await self._client.chat.stream_async(
            model=model,
            messages=[m.to_dict() for m in messages],
            temperature=temperature,
            max_tokens=max_tokens,
            stop=stop,
        )
        async for event in stream:
            delta = event.data.choices[0].delta
            yield LLMChunk(
                content=delta.content or "",
                finish_reason=event.data.choices[0].finish_reason,
                model=model,
            )

    def get_available_models(self) -> List[ModelInfo]:
        return [
            ModelInfo("mistral-large-latest", ProviderType.MISTRAL,
                      "Mistral Large", 128_000, 4_096, 0.002, 0.006,
                      True, True, False,
                      ["research","writing","code","analysis"]),
            ModelInfo("mistral-small-latest", ProviderType.MISTRAL,
                      "Mistral Small", 128_000, 4_096, 0.0001, 0.0003,
                      True, True, False,
                      ["classification","summarization","routing"]),
            ModelInfo("codestral-latest", ProviderType.MISTRAL,
                      "Codestral", 256_000, 8_096, 0.0003, 0.0009,
                      True, True, False,
                      ["code","analysis","debugging"]),
        ]


# ── Ollama Provider (Local) ───────────────────────────────────────────

class OllamaProvider(BaseLLMProvider):
    """Provider for locally-hosted models via Ollama REST API."""

    async def initialize(self) -> None:
        import aiohttp
        self._base_url = self.config.base_url or "http://localhost:11434"
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.config.timeout_seconds)
        )
        logger.info(f"Ollama provider initialized at {self._base_url}")

    async def complete(self, messages: List[Message], model: Optional[str] = None,
                       temperature: float = 0.7, max_tokens: int = 4096,
                       stop: Optional[List[str]] = None, **kwargs) -> LLMResponse:
        model = model or self.config.default_model or "llama3"
        start = time.time()
        payload = {
            "model": model,
            "messages": [m.to_dict() for m in messages],
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if stop:
            payload["options"]["stop"] = stop
        try:
            async with self._session.post(
                f"{self._base_url}/api/chat", json=payload
            ) as resp:
                data = await resp.json()
            latency = (time.time() - start) * 1000
            input_tokens = data.get("prompt_eval_count", 0)
            output_tokens = data.get("eval_count", 0)
            usage = TokenUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
            )
            return LLMResponse(
                content=data.get("message", {}).get("content", ""),
                model=model, provider=ProviderType.OLLAMA,
                usage=usage, finish_reason="stop",
                latency_ms=latency,
            )
        except Exception as e:
            return LLMResponse(
                content="", model=model, provider=ProviderType.OLLAMA,
                success=False, error=str(e),
                latency_ms=(time.time() - start) * 1000,
            )

    async def stream_complete(self, messages: List[Message],
                               model: Optional[str] = None,
                               temperature: float = 0.7,
                               max_tokens: int = 4096,
                               stop: Optional[List[str]] = None,
                               **kwargs) -> AsyncIterator[LLMChunk]:
        model = model or self.config.default_model or "llama3"
        payload = {
            "model": model,
            "messages": [m.to_dict() for m in messages],
            "stream": True,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if stop:
            payload["options"]["stop"] = stop
        async with self._session.post(
            f"{self._base_url}/api/chat", json=payload
        ) as resp:
            async for line in resp.content:
                if not line.strip():
                    continue
                data = json.loads(line)
                yield LLMChunk(
                    content=data.get("message", {}).get("content", ""),
                    finish_reason="stop" if data.get("done") else None,
                    model=model,
                )

    def get_available_models(self) -> List[ModelInfo]:
        return [
            ModelInfo("llama3", ProviderType.OLLAMA, "LLaMA 3",
                      128_000, 4_096, 0.0, 0.0, True, False, False,
                      ["research","writing","code","analysis"]),
            ModelInfo("codellama", ProviderType.OLLAMA, "Code LLaMA",
                      128_000, 4_096, 0.0, 0.0, True, False, False,
                      ["code","debugging"]),
            ModelInfo("mixtral", ProviderType.OLLAMA, "Mixtral",
                      32_000, 4_096, 0.0, 0.0, True, False, False,
                      ["research","writing","analysis"]),
            ModelInfo("deepseek-r1", ProviderType.OLLAMA, "DeepSeek R1",
                      128_000, 8_096, 0.0, 0.0, True, False, False,
                      ["reasoning","code","math"]),
        ]

    async def close(self) -> None:
        if hasattr(self, "_session") and self._session:
            await self._session.close()


# ── Provider Factory ──────────────────────────────────────────────────

PROVIDER_MAP = {
    ProviderType.OPENAI:       OpenAIProvider,
    ProviderType.ANTHROPIC:    AnthropicProvider,
    ProviderType.AZURE_OPENAI: AzureOpenAIProvider,
    ProviderType.GEMINI:       GeminiProvider,
    ProviderType.MISTRAL:      MistralProvider,
    ProviderType.OLLAMA:       OllamaProvider,
}


def create_provider(config: ProviderConfig) -> BaseLLMProvider:
    cls = PROVIDER_MAP.get(config.provider_type)
    if cls is None:
        raise ValueError(f"Unknown provider: {config.provider_type}")
    return cls(config)
