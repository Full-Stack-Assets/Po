"""
Runtime Configuration — config_api.py
Provider management, constraint tuning, trust-layer settings.
"""

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any, Optional, TYPE_CHECKING
import time

if TYPE_CHECKING:
    from orchestrator_agent.orchestrator import OrchestratorAgent

from orchestrator_agent.llm_providers import Message, ProviderType


@dataclass
class ProviderSetting:
    provider: str
    enabled: bool
    api_key_set: bool
    default_model: str
    models_available: list[str] = field(default_factory=list)
    health: dict = field(default_factory=dict)


@dataclass
class ConstraintSetting:
    name: str
    current_used: float
    max_value: float
    unit: str


@dataclass
class TrustSettings:
    auto_approve: bool
    live_signals: bool
    fail_on_unverified: bool
    approval_ttl_seconds: int
    validation_threshold: str


@dataclass
class SystemConfig:
    providers: list[ProviderSetting] = field(default_factory=list)
    constraints: list[ConstraintSetting] = field(default_factory=list)
    trust: TrustSettings = field(default_factory=lambda: TrustSettings(
        auto_approve=True,
        live_signals=False,
        fail_on_unverified=False,
        approval_ttl_seconds=3600,
        validation_threshold="green",
    ))
    tools: list[dict] = field(default_factory=list)
    environment: str = "development"


class ConfigManager:

    def __init__(self, orchestrator: "OrchestratorAgent"):
        self._orch = orchestrator

    async def get_config(self) -> SystemConfig:
        llm = self._orch.llm
        ce = self._orch.constraint_engine

        providers: list[ProviderSetting] = []
        for ptype, config in llm._configs.items():
            health_obj = llm._health.get(ptype)
            models = []
            prov_inst = llm._providers.get(ptype)
            if prov_inst:
                models = [m.model_id for m in prov_inst.get_available_models()]
            providers.append(ProviderSetting(
                provider=ptype.value,
                enabled=config.enabled and ptype in llm._providers,
                api_key_set=bool(config.api_key),
                default_model=config.default_model,
                models_available=models,
                health={
                    "circuit_open": health_obj.circuit_open if health_obj else False,
                    "success_rate": round(health_obj.success_rate, 4) if health_obj else 1.0,
                    "avg_latency_ms": round(health_obj.avg_latency_ms, 1) if health_obj else 0.0,
                },
            ))

        constraints: list[ConstraintSetting] = []
        for c in ce._constraints.values():
            constraints.append(ConstraintSetting(
                name=c.name,
                current_used=round(c.current_value, 6),
                max_value=c.max_value,
                unit=c.unit,
            ))

        trust_cfg = self._orch.config.get("trust_layer", {})
        auto_approve = True
        if self._orch.approval_manager is not None:
            auto_approve = self._orch.approval_manager.auto_approve
        live_signals = trust_cfg.get("live_signals", False)
        fail_on_unverified = False
        if hasattr(self._orch, "verification_layer") and self._orch.verification_layer:
            fail_on_unverified = self._orch.verification_layer.fail_on_unverified
        approval_ttl = trust_cfg.get("approval_ttl_seconds", 3600)
        validation_threshold = trust_cfg.get("validation_threshold", "green")

        trust = TrustSettings(
            auto_approve=auto_approve,
            live_signals=live_signals,
            fail_on_unverified=fail_on_unverified,
            approval_ttl_seconds=approval_ttl,
            validation_threshold=validation_threshold,
        )

        tools: list[dict] = []
        from orchestrator_agent.tools import default_tool_registry
        registry = default_tool_registry(self._orch.llm)
        for spec in registry.list_tools():
            tools.append({
                "name": spec.get("name", ""),
                "description": spec.get("description", ""),
                "enabled": True,
            })

        environment = self._orch.config.get("environment", "development")

        return SystemConfig(
            providers=providers,
            constraints=constraints,
            trust=trust,
            tools=tools,
            environment=environment,
        )

    async def update_constraints(
        self,
        max_tokens: Optional[float] = None,
        max_cost: Optional[float] = None,
    ) -> list[ConstraintSetting]:
        ce = self._orch.constraint_engine
        if max_tokens is not None:
            c = ce._constraints.get("token_budget")
            if c:
                c.max_value = max_tokens
        if max_cost is not None:
            c = ce._constraints.get("cost_budget")
            if c:
                c.max_value = max_cost
        return [
            ConstraintSetting(
                name=c.name,
                current_used=round(c.current_value, 6),
                max_value=c.max_value,
                unit=c.unit,
            )
            for c in ce._constraints.values()
        ]

    async def update_trust_settings(self, **kwargs: Any) -> TrustSettings:
        trust_cfg = self._orch.config.setdefault("trust_layer", {})

        if "auto_approve" in kwargs:
            val = kwargs["auto_approve"]
            trust_cfg["auto_approve"] = val
            if self._orch.approval_manager is not None:
                self._orch.approval_manager.auto_approve = val

        if "live_signals" in kwargs:
            trust_cfg["live_signals"] = kwargs["live_signals"]

        if "fail_on_unverified" in kwargs:
            val = kwargs["fail_on_unverified"]
            trust_cfg["fail_on_unverified"] = val
            if hasattr(self._orch, "verification_layer") and self._orch.verification_layer:
                self._orch.verification_layer.fail_on_unverified = val

        if "approval_ttl_seconds" in kwargs:
            trust_cfg["approval_ttl_seconds"] = kwargs["approval_ttl_seconds"]

        if "validation_threshold" in kwargs:
            trust_cfg["validation_threshold"] = kwargs["validation_threshold"]

        auto_approve = trust_cfg.get("auto_approve", True)
        if self._orch.approval_manager is not None:
            auto_approve = self._orch.approval_manager.auto_approve

        fail_on_unverified = trust_cfg.get("fail_on_unverified", False)
        if hasattr(self._orch, "verification_layer") and self._orch.verification_layer:
            fail_on_unverified = self._orch.verification_layer.fail_on_unverified

        return TrustSettings(
            auto_approve=auto_approve,
            live_signals=trust_cfg.get("live_signals", False),
            fail_on_unverified=fail_on_unverified,
            approval_ttl_seconds=trust_cfg.get("approval_ttl_seconds", 3600),
            validation_threshold=trust_cfg.get("validation_threshold", "green"),
        )

    async def test_provider(self, provider: str) -> dict:
        try:
            ptype = ProviderType(provider)
        except ValueError:
            return {"success": False, "latency_ms": 0, "model": "", "error": f"Unknown provider: {provider}"}

        llm = self._orch.llm
        prov_inst = llm._providers.get(ptype)
        if not prov_inst:
            return {"success": False, "latency_ms": 0, "model": "", "error": f"Provider {provider} not initialized"}

        config = llm._configs.get(ptype)
        model = config.default_model if config else ""

        start = time.time()
        try:
            resp = await prov_inst.complete(
                messages=[Message(role="user", content="ping")],
                model=model,
                temperature=0.0,
                max_tokens=1,
            )
            latency_ms = round((time.time() - start) * 1000, 1)
            return {
                "success": resp.success,
                "latency_ms": latency_ms,
                "model": model,
                "error": resp.error or "",
            }
        except Exception as exc:
            latency_ms = round((time.time() - start) * 1000, 1)
            return {"success": False, "latency_ms": latency_ms, "model": model, "error": str(exc)}

    async def reset_provider_circuit(self, provider: str) -> bool:
        try:
            ptype = ProviderType(provider)
        except ValueError:
            return False

        health = self._orch.llm._health.get(ptype)
        if health is None:
            return False

        health.circuit_open = False
        health.circuit_open_until = 0.0
        health.consecutive_failures = 0
        return True

    async def reset_budgets(self) -> list[ConstraintSetting]:
        ce = self._orch.constraint_engine
        ce.reset_all()
        return [
            ConstraintSetting(
                name=c.name,
                current_used=round(c.current_value, 6),
                max_value=c.max_value,
                unit=c.unit,
            )
            for c in ce._constraints.values()
        ]

    async def get_provider_models(self, provider: str) -> list[dict]:
        try:
            ptype = ProviderType(provider)
        except ValueError:
            return []

        prov_inst = self._orch.llm._providers.get(ptype)
        if not prov_inst:
            return []

        return [
            {
                "model_id": m.model_id,
                "display_name": m.display_name,
                "context_window": m.context_window,
                "max_output_tokens": m.max_output_tokens,
                "cost_per_1k_input": m.cost_per_1k_input,
                "cost_per_1k_output": m.cost_per_1k_output,
                "supports_streaming": m.supports_streaming,
                "supports_tools": m.supports_tools,
                "supports_vision": m.supports_vision,
                "capabilities": m.capabilities,
            }
            for m in prov_inst.get_available_models()
        ]


def config_to_dict(config: SystemConfig) -> dict:
    return {
        "providers": [asdict(p) for p in config.providers],
        "constraints": [asdict(c) for c in config.constraints],
        "trust": asdict(config.trust),
        "tools": config.tools,
        "environment": config.environment,
    }
