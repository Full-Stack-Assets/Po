"""Unit tests for the validation gate."""

import pytest

from orchestrator_agent.validation import ValidationGate, ValidationScore


@pytest.mark.asyncio
async def test_rich_b2b_idea_scores_higher_than_vague():
    gate = ValidationGate()  # heuristic backend (no LLM)
    strong = await gate.validate(
        "A paid B2B SaaS tool for indie SaaS founders that automates "
        "validated cold outbound with per-month pricing"
    )
    weak = await gate.validate("an app")
    assert strong.overall_score > weak.overall_score
    assert strong.backend == "heuristic"


@pytest.mark.asyncio
async def test_empty_idea_is_blocking_red():
    gate = ValidationGate()
    result = await gate.validate("")
    assert result.score == ValidationScore.RED
    assert result.is_blocking is True
    assert result.override_required is True


@pytest.mark.asyncio
async def test_thresholds_assign_ratings():
    gate = ValidationGate(green_threshold=70, red_threshold=40)
    strong = await gate.validate(
        "A paid B2B SaaS subscription for marketing agencies and teams "
        "with clear pricing and enterprise revenue potential for founders"
    )
    assert strong.score == ValidationScore.GREEN
    assert strong.is_blocking is False


@pytest.mark.asyncio
async def test_scores_are_bounded_and_serializable():
    gate = ValidationGate()
    result = await gate.validate("A vertical AI operator for B2B SaaS")
    for s in (result.demand_score, result.competitor_score,
              result.icp_score, result.wtp_score, result.overall_score):
        assert 0 <= s <= 100
    d = result.to_dict()
    assert d["score"] in {"red", "yellow", "green"}
    assert "rationale" in d


@pytest.mark.asyncio
async def test_llm_backend_used_when_available():
    class FakeResp:
        success = True
        content = '{"demand": 90, "competitor": 80, "icp": 85, "wtp": 88}'

    class FakeLLM:
        async def complete(self, **kwargs):
            return FakeResp()

    gate = ValidationGate(FakeLLM())
    result = await gate.validate("anything")
    assert result.backend == "llm"
    assert result.score == ValidationScore.GREEN


@pytest.mark.asyncio
async def test_llm_failure_falls_back_to_heuristic():
    class FakeLLM:
        async def complete(self, **kwargs):
            raise RuntimeError("provider down")

    gate = ValidationGate(FakeLLM())
    result = await gate.validate("A paid B2B SaaS for founders")
    assert result.backend == "heuristic"


def test_with_live_signals_wires_scorers():
    gate = ValidationGate.with_live_signals()
    assert gate.scorers is not None
    assert set(gate.scorers.keys()) == {"demand", "competitor", "icp", "wtp"}


@pytest.mark.asyncio
async def test_live_signals_composite_backend():
    async def fake_fetch(url):
        return []  # empty results → scorers fall back to heuristic per-dim

    gate = ValidationGate.with_live_signals(fetch=fake_fetch)
    result = await gate.validate("A paid B2B SaaS for indie founders")
    assert result.backend == "composite"
    assert "sources" in result.details
