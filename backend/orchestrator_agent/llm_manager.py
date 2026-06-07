"""
LLM Manager — llm_manager.py
Multi-provider coordinator with intelligent model selection, fallback chains,
constraint-aware routing, and provider health tracking.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple
from collections import defaultdict
import asyncio
import logging
import time

from orchestrator_agent.llm_providers import (
    BaseLLMProvider, ProviderConfig, ProviderType, ModelInfo,
    Message, LLMResponse, LLMChunk, TokenUsage, create_provider,
    estimate_cost,
)

logger = logging.getLogger(__name__)


# ── Provider Health Tracking ──────────────────────────────────────────

@dataclass
class ProviderHealth:
    """Tracks reliability metrics for a single provider."""
    provider: ProviderType
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_latency_ms: float = 0.0
    consecutive_failures: int = 0
    last_failure_time: float = 0.0
    circuit_open: bool = False
    circuit_open_until: float = 0.0

    @property
    def success_rate(self) -> float:
        if self.total_requests == 0:
            return 1.0
        return self.successful_requests / self.total_requests

    @property
    def avg_latency_ms(self) -> float:
        if self.successful_requests == 0:
            return 0.0
        return self.total_latency_ms / self.successful_requests

    def record_success(self, latency_ms: float) -> None:
        self.total_requests += 1
        self.successful_requests += 1
        self.total_latency_ms += latency_ms
        self.consecutive_failures = 0

    def record_failure(self) -> None:
        self.total_requests += 1
        self.failed_requests += 1
        self.consecutive_failures += 1
        self.last_failure_time = time.time()
        # Circuit breaker: open after 3 consecutive failures
        if self.consecutive_failures >= 3:
            self.circuit_open = True
            self.circuit_open_until = time.time() + 60  # 60s cooldown
            logger.warning(
                f"Circuit breaker OPEN for {self.provider.value} "
                f"(3 consecutive failures, cooldown 60s)"
            )

    def is_available(self) -> bool:
        if not self.circuit_open:
            return True
        if time.time() > self.circuit_open_until:
            self.circuit_open = False
            self.consecutive_failures = 0
            logger.info(f"Circuit breaker CLOSED for {self.provider.value}")
            return True
        return False


# ── Fallback Chain ────────────────────────────────────────────────────

@dataclass
class FallbackChain:
    """Ordered list of (provider, model) pairs to try for a given capability."""
    name: str
    steps: List[Tuple[ProviderType, str]] = field(default_factory=list)

    def add(self, provider: ProviderType, model: str) -> "FallbackChain":
        self.steps.append((provider, model))
        return self


# ── Model Selection Strategy ─────────────────────────────────────────

class ModelSelector:
    """Selects the optimal model based on task requirements and constraints."""

    CAPABILITY_RANKING: Dict[str, List[Tuple[ProviderType, str, float]]] = {
        "research": [
            (ProviderType.OPENAI,    "gpt-4.1",              0.95),
            (ProviderType.ANTHROPIC, "claude-sonnet-4-5",     0.93),
            (ProviderType.GEMINI,    "gemini-2.5-pro",        0.91),
            (ProviderType.MISTRAL,   "mistral-large-latest",  0.85),
            (ProviderType.OLLAMA,    "llama3",                0.70),
        ],
        "writing": [
            (ProviderType.ANTHROPIC, "claude-sonnet-4-5",     0.96),
            (ProviderType.OPENAI,    "gpt-4.1",              0.94),
            (ProviderType.GEMINI,    "gemini-2.5-pro",        0.90),
            (ProviderType.MISTRAL,   "mistral-large-latest",  0.84),
            (ProviderType.OLLAMA,    "llama3",                0.68),
        ],
        "code": [
            (ProviderType.ANTHROPIC, "claude-sonnet-4-5",     0.97),
            (ProviderType.OPENAI,    "o4-mini",               0.95),
            (ProviderType.GEMINI,    "gemini-2.5-pro",        0.92),
            (ProviderType.MISTRAL,   "codestral-latest",      0.88),
            (ProviderType.OLLAMA,    "codellama",             0.72),
        ],
        "analysis": [
            (ProviderType.OPENAI,    "o4-mini",               0.96),
            (ProviderType.ANTHROPIC, "claude-sonnet-4-5",     0.94),
            (ProviderType.GEMINI,    "gemini-2.5-pro",        0.92),
            (ProviderType.MISTRAL,   "mistral-large-latest",  0.86),
            (ProviderType.OLLAMA,    "deepseek-r1",           0.75),
        ],
        "classification": [
            (ProviderType.OPENAI,    "gpt-4.1-nano",          0.90),
            (ProviderType.GEMINI,    "gemini-2.0-flash",      0.88),
            (ProviderType.MISTRAL,   "mistral-small-latest",  0.86),
            (ProviderType.ANTHROPIC, "claude-haiku-3.5",      0.85),
            (ProviderType.OLLAMA,    "llama3",                0.65),
        ],
        "summarization": [
            (ProviderType.GEMINI,    "gemini-2.5-flash",      0.93),
            (ProviderType.OPENAI,    "gpt-4.1-mini",          0.91),
            (ProviderType.ANTHROPIC, "claude-haiku-3.5",      0.89),
            (ProviderType.MISTRAL,   "mistral-small-latest",  0.84),
            (ProviderType.OLLAMA,    "llama3",                0.66),
        ],
    }

    @classmethod
    def select(
        cls,
        capability: str,
        available_providers: set[ProviderType],
        health: Dict[ProviderType, ProviderHealth],
        max_cost_per_1k: float = float("inf"),
        prefer_local: bool = False,
    ) -> List[Tuple[ProviderType, str, float]]:
        """Return ranked (provider, model, quality_score) for a capability."""
        rankings = cls.CAPABILITY_RANKING.get(capability, [])
        candidates = []
        for provider, model, quality in rankings:
            if provider not in available_providers:
                continue
            h = health.get(provider)
            if h and not h.is_available():
                continue
            ic, oc, _ = estimate_cost(model, 1000, 1000)
            if (ic + oc) > max_cost_per_1k:
                continue
            # Adjust score based on health
            adjusted = quality
            if h and h.success_rate < 1.0:
                adjusted *= h.success_rate
            if prefer_local and provider == ProviderType.OLLAMA:
                adjusted *= 1.15  # 15% boost for local
            candidates.append((provider, model, adjusted))

        candidates.sort(key=lambda x: x[2], reverse=True)
        return candidates


# ── LLM Manager ──────────────────────────────────────────────────────

class LLMManager:
    """
    Central manager that coordinates multiple LLM providers.
    Features:
    - Multi-provider initialization and lifecycle management
    - Intelligent model selection per task capability
    - Automatic fallback chains with circuit breakers
    - Cost and token tracking across all providers
    - Constraint-aware model routing
    """

    def __init__(self):
        self._providers: Dict[ProviderType, BaseLLMProvider] = {}
        self._configs: Dict[ProviderType, ProviderConfig] = {}
        self._health: Dict[ProviderType, ProviderHealth] = {}
        self._fallback_chains: Dict[str, FallbackChain] = {}
        self._total_usage = TokenUsage()
        self._initialized = False

    # ── Setup ─────────────────────────────────────────────────────────

    def add_provider(self, config: ProviderConfig) -> None:
        """Register a provider configuration (must call initialize() after)."""
        self._configs[config.provider_type] = config
        self._health[config.provider_type] = ProviderHealth(
            provider=config.provider_type
        )

    def add_fallback_chain(self, chain: FallbackChain) -> None:
        self._fallback_chains[chain.name] = chain

    async def initialize(self) -> None:
        """Initialize all registered providers concurrently."""
        tasks = []
        for ptype, config in self._configs.items():
            if not config.enabled:
                continue
            provider = create_provider(config)
            self._providers[ptype] = provider
            tasks.append(self._safe_init(ptype, provider))
        await asyncio.gather(*tasks)
        self._initialized = True
        logger.info(
            f"LLMManager initialized with {len(self._providers)} providers: "
            f"{[p.value for p in self._providers]}"
        )

    async def _safe_init(self, ptype: ProviderType,
                          provider: BaseLLMProvider) -> None:
        try:
            await provider.initialize()
        except Exception as e:
            logger.error(f"Failed to initialize {ptype.value}: {e}")
            self._health[ptype].record_failure()

    async def shutdown(self) -> None:
        """Gracefully close all provider connections."""
        for provider in self._providers.values():
            await provider.close()
        self._providers.clear()

    # ── Core Completion ───────────────────────────────────────────────

    async def complete(
        self,
        messages: List[Message],
        capability: str = "research",
        provider: Optional[ProviderType] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        max_cost_per_1k: float = float("inf"),
        prefer_local: bool = False,
        fallback_chain: Optional[str] = None,
        **kwargs,
    ) -> LLMResponse:
        """
        Send a completion request with intelligent routing.

        Priority order:
        1. Explicit provider + model
        2. Named fallback chain
        3. Capability-based auto-selection with fallback
        """
        if provider and model:
            return await self._try_complete(
                provider, model, messages, temperature, max_tokens, **kwargs
            )

        # Build candidate list
        if fallback_chain and fallback_chain in self._fallback_chains:
            chain = self._fallback_chains[fallback_chain]
            candidates = [
                (p, m, 1.0) for p, m in chain.steps
                if p in self._providers
            ]
        else:
            candidates = ModelSelector.select(
                capability,
                set(self._providers.keys()),
                self._health,
                max_cost_per_1k=max_cost_per_1k,
                prefer_local=prefer_local,
            )

        if not candidates:
            return LLMResponse(
                content="", model="none",
                provider=ProviderType.OPENAI,
                success=False,
                error="No eligible provider/model for this request",
            )

        # Try candidates in order (automatic fallback)
        last_error = ""
        for prov_type, model_id, score in candidates:
            resp = await self._try_complete(
                prov_type, model_id, messages,
                temperature, max_tokens, **kwargs
            )
            if resp.success:
                return resp
            last_error = resp.error or "Unknown error"
            logger.warning(
                f"Fallback: {prov_type.value}/{model_id} failed — {last_error}"
            )

        return LLMResponse(
            content="", model="fallback_exhausted",
            provider=ProviderType.OPENAI,
            success=False,
            error=f"All providers failed. Last error: {last_error}",
        )

    async def _try_complete(
        self,
        prov_type: ProviderType,
        model: str,
        messages: List[Message],
        temperature: float,
        max_tokens: int,
        **kwargs,
    ) -> LLMResponse:
        provider = self._providers.get(prov_type)
        if not provider:
            return LLMResponse(
                content="", model=model, provider=prov_type,
                success=False, error=f"Provider {prov_type.value} not available",
            )

        health = self._health.get(prov_type)
        if health and not health.is_available():
            return LLMResponse(
                content="", model=model, provider=prov_type,
                success=False, error=f"Circuit breaker open for {prov_type.value}",
            )

        resp = await provider.complete(
            messages, model=model, temperature=temperature,
            max_tokens=max_tokens, **kwargs,
        )

        if health:
            if resp.success:
                health.record_success(resp.latency_ms)
            else:
                health.record_failure()

        # Accumulate global usage
        if resp.success:
            self._total_usage.input_tokens += resp.usage.input_tokens
            self._total_usage.output_tokens += resp.usage.output_tokens
            self._total_usage.total_tokens += resp.usage.total_tokens
            self._total_usage.input_cost += resp.usage.input_cost
            self._total_usage.output_cost += resp.usage.output_cost
            self._total_usage.total_cost += resp.usage.total_cost

        return resp

    # ── Streaming ─────────────────────────────────────────────────────

    async def stream_complete(
        self,
        messages: List[Message],
        capability: str = "research",
        provider: Optional[ProviderType] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs,
    ) -> AsyncIterator[LLMChunk]:
        """Stream a completion from the best available provider."""
        if not provider or not model:
            candidates = ModelSelector.select(
                capability, set(self._providers.keys()), self._health
            )
            if candidates:
                provider, model, _ = candidates[0]
            else:
                yield LLMChunk(content="[Error: No provider available]",
                               finish_reason="error")
                return

        prov = self._providers.get(provider)
        if not prov:
            yield LLMChunk(content="[Error: Provider not found]",
                           finish_reason="error")
            return

        async for chunk in prov.stream_complete(
            messages, model=model, temperature=temperature,
            max_tokens=max_tokens, **kwargs
        ):
            yield chunk

    # ── Batch / Parallel ──────────────────────────────────────────────

    async def complete_batch(
        self,
        requests: List[Dict[str, Any]],
        max_concurrency: int = 5,
    ) -> List[LLMResponse]:
        """Execute multiple completion requests with concurrency control."""
        sem = asyncio.Semaphore(max_concurrency)

        async def _limited(req: Dict) -> LLMResponse:
            async with sem:
                return await self.complete(**req)

        return await asyncio.gather(
            *[_limited(r) for r in requests]
        )

    # ── Observability ─────────────────────────────────────────────────

    def get_usage(self) -> Dict[str, Any]:
        return {
            "input_tokens": self._total_usage.input_tokens,
            "output_tokens": self._total_usage.output_tokens,
            "total_tokens": self._total_usage.total_tokens,
            "total_cost_usd": round(self._total_usage.total_cost, 6),
        }

    def get_health(self) -> List[Dict[str, Any]]:
        return [
            {
                "provider": h.provider.value,
                "total_requests": h.total_requests,
                "success_rate": f"{h.success_rate:.1%}",
                "avg_latency_ms": round(h.avg_latency_ms, 1),
                "consecutive_failures": h.consecutive_failures,
                "circuit_open": h.circuit_open,
            }
            for h in self._health.values()
        ]

    def get_available_models(self) -> List[Dict[str, Any]]:
        models = []
        for provider in self._providers.values():
            for m in provider.get_available_models():
                models.append({
                    "model": m.model_id,
                    "provider": m.provider.value,
                    "name": m.display_name,
                    "context_window": m.context_window,
                    "cost_input_1k": m.cost_per_1k_input,
                    "cost_output_1k": m.cost_per_1k_output,
                    "capabilities": m.capabilities,
                })
        return models
