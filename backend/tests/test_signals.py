"""Unit tests for live validation signal scorers."""

import pytest

from orchestrator_agent.signals import (
    core_keyword, GoogleSuggestDemandScorer, SuggestCompetitorScorer,
    RedditWTPScorer, HeuristicICPScorer,
)
from orchestrator_agent.validation import ValidationGate, ValidationScore


def test_core_keyword_strips_stopwords():
    kw = core_keyword("A tool for the founders of a startup")
    assert "the" not in kw.split()
    assert "founders" in kw


@pytest.mark.asyncio
async def test_demand_scorer_uses_suggestion_count():
    async def fetch(url):
        return ["kw", ["a", "b", "c", "d", "e"]]  # 5 suggestions

    sub = await GoogleSuggestDemandScorer(fetch).score("an idea")
    assert sub is not None
    assert sub.source == "google_suggest"
    assert sub.value == 60  # 20 + 5*8
    assert sub.details["suggestions"] == 5


@pytest.mark.asyncio
async def test_demand_scorer_returns_none_on_bad_data():
    async def fetch(url):
        return None

    assert await GoogleSuggestDemandScorer(fetch).score("x") is None


@pytest.mark.asyncio
async def test_competitor_scorer_more_completions_less_room():
    async def few(url):
        return ["kw", ["a"]]

    async def many(url):
        return ["kw", ["a", "b", "c", "d", "e", "f", "g"]]

    crowded = await SuggestCompetitorScorer(many).score("idea")
    open_field = await SuggestCompetitorScorer(few).score("idea")
    assert open_field.value > crowded.value


@pytest.mark.asyncio
async def test_reddit_wtp_counts_pricing_mentions():
    async def fetch(url):
        return {"data": {"children": [
            {"data": {"title": "Would you pay for this?",
                      "selftext": "I'd pay $20/mo"}},
            {"data": {"title": "cool idea", "selftext": "just a thought"}},
        ]}}

    sub = await RedditWTPScorer(fetch).score("idea")
    assert sub.source == "reddit"
    assert sub.details["wtp_hits"] == 1
    assert sub.value == 35  # 25 + 1*10


@pytest.mark.asyncio
async def test_reddit_wtp_no_posts():
    async def fetch(url):
        return {"data": {"children": []}}

    sub = await RedditWTPScorer(fetch).score("idea")
    assert sub.details["posts"] == 0


@pytest.mark.asyncio
async def test_icp_scorer_rewards_named_audience():
    named = await HeuristicICPScorer().score("a tool for b2b saas founders")
    vague = await HeuristicICPScorer().score("a cool thing")
    assert named.value > vague.value


@pytest.mark.asyncio
async def test_gate_with_live_signals_uses_scorers_and_falls_back():
    async def demand_fetch(url):
        # Only the demand keyword endpoint returns data; others fail -> None.
        if "best" in url or "reddit" in url:
            return None
        return ["kw", ["a", "b", "c"]]

    gate = ValidationGate.with_live_signals(fetch=demand_fetch)
    result = await gate.validate("A paid B2B SaaS for founders")
    assert result.backend == "composite"
    sources = result.details["sources"]
    assert sources["demand"] == "google_suggest"
    assert sources["competitor"] == "heuristic(fallback)"
    assert sources["wtp"] == "heuristic(fallback)"
    assert sources["icp"] == "heuristic"  # HeuristicICPScorer always returns
    assert result.score in (ValidationScore.RED, ValidationScore.YELLOW,
                            ValidationScore.GREEN)
