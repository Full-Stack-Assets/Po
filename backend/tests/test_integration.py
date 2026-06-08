"""End-to-end integration tests through the real OrchestratorAgent.

These tests exercise the full wiring path (initialization, intent
classification, routing, pipeline, trust layer, persistence, checkpoints)
using a fake LLM provider that returns realistic responses — catching
serialization, prompt, and configuration bugs that unit stubs miss.
"""

import json
import pytest

from orchestrator_agent.llm_providers import (
    BaseLLMProvider, ProviderConfig, ProviderType,
    LLMResponse, LLMChunk, TokenUsage, ModelInfo,
)
from orchestrator_agent.orchestrator import OrchestratorAgent


# ── Fake LLM provider ────────────────────────────────────────────────

_PLAN_JSON = json.dumps([
    {"description": "Research competitor landscape for B2B SaaS",
     "agent_type": "research", "complexity": "medium"},
    {"description": "Draft a cold outreach email template",
     "agent_type": "write", "complexity": "low"},
    {"description": "Summarize findings into a one-pager",
     "agent_type": "summarize", "complexity": "low"},
])


class FakeProvider(BaseLLMProvider):
    """Returns canned responses keyed on intent signals in the messages."""

    def __init__(self, config: ProviderConfig):
        super().__init__(config)

    async def initialize(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def complete(self, messages, model=None, temperature=0.7,
                       max_tokens=4096, stop=None, **kwargs) -> LLMResponse:
        prompt = " ".join(m.content for m in messages).lower()
        # Intent classifier prompt → return the intent label.
        if "classify" in prompt and "categories:" in prompt:
            user_msg = messages[-1].content.lower()
            if "plan" in user_msg or "decompose" in user_msg:
                content = "plan"
            elif "research" in user_msg:
                content = "research"
            elif "write" in user_msg or "draft" in user_msg:
                content = "write"
            elif "summarize" in user_msg:
                content = "summarize"
            else:
                content = "research"
        # Planner prompt → return a JSON plan.
        elif "task decomposition specialist" in prompt:
            content = _PLAN_JSON
        # Validation scorer → return JSON scores.
        elif "demand-validation" in prompt:
            content = json.dumps({
                "demand": 75, "competitor": 70, "icp": 80, "wtp": 65,
            })
        # Default: a generic successful response.
        else:
            content = f"Completed: {messages[-1].content[:80]}"

        return LLMResponse(
            content=content,
            model=self.config.default_model,
            provider=self.config.provider_type,
            usage=TokenUsage(input_tokens=50, output_tokens=100,
                             total_tokens=150, total_cost=0.001),
            success=True,
        )

    async def stream_complete(self, messages, model=None, temperature=0.7,
                              max_tokens=4096, stop=None, **kwargs):
        resp = await self.complete(messages, model, temperature, max_tokens)
        for word in resp.content.split():
            yield LLMChunk(content=word + " ", model=resp.model)

    def get_available_models(self):
        return [ModelInfo(model_id="fake-model", provider=ProviderType.OPENAI,
                          display_name="Fake Model")]


# Monkey-patch create_provider so LLMManager uses our fake.
import orchestrator_agent.llm_manager as _mgr
_orig_create = _mgr.create_provider


def _fake_create(config: ProviderConfig) -> BaseLLMProvider:
    return FakeProvider(config)


@pytest.fixture(autouse=True)
def _patch_provider(monkeypatch):
    monkeypatch.setattr(_mgr, "create_provider", _fake_create)


FAKE_CONFIG = ProviderConfig(
    provider_type=ProviderType.OPENAI,
    api_key="fake-key",
    default_model="fake-model",
)


# ── Tests ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_full_orchestrate_roundtrip():
    """Single orchestration request through the real OrchestratorAgent."""
    orch = OrchestratorAgent(config={
        "trust_layer": {"auto_approve": True},
    })
    await orch.initialize(provider_configs=[FAKE_CONFIG])
    try:
        result = await orch.orchestrate("Research the AI agent market")
        assert result["success"] is True
        assert result["output"]
        assert result["intent"] == "research"
        assert result["cost_usd"] >= 0
        assert result["provider_used"] == "openai"
        assert result["constraints"]
    finally:
        await orch.shutdown()


@pytest.mark.asyncio
async def test_full_orchestrate_with_validation():
    """Orchestration with the validation gate enabled."""
    orch = OrchestratorAgent(config={
        "trust_layer": {"auto_approve": True},
    })
    await orch.initialize(provider_configs=[FAKE_CONFIG])
    try:
        result = await orch.orchestrate(
            "A paid B2B SaaS tool for indie founders",
            validate=True,
        )
        assert result["success"] is True
        assert result["validation"] is not None
        assert result["validation"]["score"] in ("red", "yellow", "green")
    finally:
        await orch.shutdown()


@pytest.mark.asyncio
async def test_full_plan_and_run_workflow():
    """PlannerAgent decomposes a goal → checkpointed workflow runs to completion."""
    orch = OrchestratorAgent(config={
        "trust_layer": {"auto_approve": True},
    })
    await orch.initialize(provider_configs=[FAKE_CONFIG])
    try:
        result = await orch.plan_and_run_workflow(
            "Grow my B2B SaaS to 100 paying users")
        assert result.get("status") == "completed"
        assert result.get("plan_raw")
        assert len(result.get("results", [])) == 3
        assert result["results"][0]["intent"] == "research"
        assert result["results"][1]["intent"] == "write"
        assert result["results"][2]["intent"] == "summarize"
    finally:
        await orch.shutdown()


@pytest.mark.asyncio
async def test_plan_workflow_with_approval_gate():
    """A planned workflow pauses on a risky 'write' step when auto_approve=False."""
    orch = OrchestratorAgent(config={
        "trust_layer": {"auto_approve": False},
    })
    await orch.initialize(provider_configs=[FAKE_CONFIG])
    try:
        result = await orch.plan_and_run_workflow(
            "Grow my B2B SaaS to 100 paying users")
        # The first step (research) succeeds; the second (write) pauses.
        assert result["status"] == "awaiting_approval"
        assert result["step_index"] == 1
        assert len(result["results"]) == 1

        # Approve and resume.
        tid = result["thread_id"]
        aid = result["pending_approval_id"]
        await orch.decide_approval(aid, approved=True)
        resumed = await orch.resume_workflow(tid)
        assert resumed["status"] == "completed"
        assert len(resumed["results"]) == 3
    finally:
        await orch.shutdown()


@pytest.mark.asyncio
async def test_persistence_records_run():
    """Orchestration run is persisted and shows up in list_runs/stats."""
    orch = OrchestratorAgent(config={
        "trust_layer": {"auto_approve": True},
    })
    await orch.initialize(provider_configs=[FAKE_CONFIG])
    try:
        await orch.orchestrate("Research market sizing")
        runs = await orch.list_runs()
        assert len(runs) >= 1
        assert runs[0]["intent"] == "research"
        assert runs[0]["success"] is True

        stats = await orch.get_reliability_stats()
        assert stats["total_runs"] >= 1
        assert stats["success_rate"] > 0
    finally:
        await orch.shutdown()


@pytest.mark.asyncio
async def test_status_and_health_endpoints():
    """get_status() and get_health() return well-formed data after init."""
    orch = OrchestratorAgent(config={})
    await orch.initialize(provider_configs=[FAKE_CONFIG])
    try:
        status = orch.get_status()
        assert status["initialized"] is True
        assert len(status["agents"]) == 6
        agent_names = {a["name"] for a in status["agents"]}
        assert "PlannerAgent" in agent_names
        assert "ResearchAgent" in agent_names
        assert len(status["constraints"]) >= 2
    finally:
        await orch.shutdown()


@pytest.mark.asyncio
async def test_batch_orchestrate():
    """Batch orchestration with concurrent execution."""
    orch = OrchestratorAgent(config={
        "trust_layer": {"auto_approve": True},
    })
    await orch.initialize(provider_configs=[FAKE_CONFIG])
    try:
        results = await orch.orchestrate_batch([
            "Research competitors",
            "Draft investor memo",
        ])
        assert len(results) == 2
        assert all(r["success"] for r in results)
    finally:
        await orch.shutdown()


@pytest.mark.asyncio
async def test_manual_workflow_roundtrip():
    """Caller-provided workflow steps run and checkpoint correctly."""
    orch = OrchestratorAgent(config={
        "trust_layer": {"auto_approve": True},
    })
    await orch.initialize(provider_configs=[FAKE_CONFIG])
    try:
        result = await orch.run_workflow(
            [{"input": "research ICP", "intent": "research"},
             {"input": "summarize findings", "intent": "summarize"}],
            thread_id="int-wf-1",
        )
        assert result["status"] == "completed"
        assert result["step_index"] == 2

        state = await orch.get_workflow("int-wf-1")
        assert state is not None
        assert state["status"] == "completed"
    finally:
        await orch.shutdown()
