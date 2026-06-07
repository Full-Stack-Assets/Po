"""
Demand-validation signal scorers — signals.py
=============================================

Pluggable scorers behind the validation gate. Each scorer measures ONE
dimension (demand, competitor density, ICP clarity, willingness-to-pay) and
returns a :class:`SubScore`, or ``None`` to signal "no usable data" so the
gate can fall back to its heuristic for that dimension.

The network-backed scorers use *real, key-free* public signals:

- **demand** — Google autocomplete (Suggest API) breadth for the core keyword.
- **competitor** — autocomplete breadth for ``best <keyword>`` (branded /
  comparison completions imply a crowded category → less room).
- **wtp** — Reddit search hits mentioning pricing / paying for the keyword.

All HTTP access goes through an injectable async ``fetch`` callable returning
parsed JSON (or ``None`` on any failure), so scorers are fully unit-testable
offline and degrade gracefully when the network/policy blocks them.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Optional
from urllib.parse import quote_plus
import json
import logging
import re

logger = logging.getLogger(__name__)

JsonFetcher = Callable[[str], Awaitable[Optional[Any]]]

_USER_AGENT = "PoValidationBot/1.0 (+https://example.com/po)"
# Audience markers shared with the heuristic ICP signal.
AUDIENCE_TERMS = ("for ", "founders", "teams", "developers", "marketers",
                  "agencies", "b2b", "smb", "saas", "ecommerce", "startups")
_STOPWORDS = {"a", "an", "the", "for", "of", "to", "and", "with", "that",
              "my", "your", "is", "in", "on"}


async def default_json_fetch(url: str, timeout: int = 8) -> Optional[Any]:
    """Fetch a URL and parse JSON; return None on any error."""
    try:
        import aiohttp
        headers = {"User-Agent": _USER_AGENT, "Accept": "application/json"}
        client_timeout = aiohttp.ClientTimeout(total=timeout)
        async with aiohttp.ClientSession(timeout=client_timeout) as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    return None
                text = await resp.text()
        return json.loads(text)
    except Exception as e:  # noqa: BLE001 — any failure → degrade gracefully
        logger.debug(f"fetch failed for {url}: {e}")
        return None


def core_keyword(idea: str, max_words: int = 5) -> str:
    """Reduce an idea to a short keyword query for search APIs."""
    words = re.findall(r"[a-z0-9]+", idea.lower())
    kept = [w for w in words if w not in _STOPWORDS]
    return " ".join(kept[:max_words]) or idea.strip()


@dataclass
class SubScore:
    """A single dimension's score (0-100) plus provenance."""
    name: str
    value: int
    source: str
    details: Dict[str, Any] = field(default_factory=dict)


class SignalScorer(ABC):
    """Scores one validation dimension. Return None to fall back to heuristic."""

    dimension: str = ""

    @abstractmethod
    async def score(self, idea: str) -> Optional[SubScore]:
        ...


def _clamp(v: float) -> int:
    return max(0, min(100, int(round(v))))


class GoogleSuggestDemandScorer(SignalScorer):
    """Demand proxy from Google autocomplete breadth."""

    dimension = "demand"
    URL = "https://suggestqueries.google.com/complete/search?client=firefox&q={q}"

    def __init__(self, fetch: Optional[JsonFetcher] = None):
        self._fetch = fetch or default_json_fetch

    async def score(self, idea: str) -> Optional[SubScore]:
        kw = core_keyword(idea)
        data = await self._fetch(self.URL.format(q=quote_plus(kw)))
        if not data or len(data) < 2 or not isinstance(data[1], list):
            return None
        n = len(data[1])
        return SubScore("demand", _clamp(20 + n * 8), "google_suggest",
                        {"keyword": kw, "suggestions": n})


class SuggestCompetitorScorer(SignalScorer):
    """Competitor-room proxy: more 'best <kw>' completions → more saturation."""

    dimension = "competitor"
    URL = "https://suggestqueries.google.com/complete/search?client=firefox&q={q}"

    def __init__(self, fetch: Optional[JsonFetcher] = None):
        self._fetch = fetch or default_json_fetch

    async def score(self, idea: str) -> Optional[SubScore]:
        kw = core_keyword(idea)
        data = await self._fetch(self.URL.format(q=quote_plus(f"best {kw}")))
        if not data or len(data) < 2 or not isinstance(data[1], list):
            return None
        n = len(data[1])
        # Higher score == more room (less crowded).
        return SubScore("competitor", _clamp(95 - n * 9), "google_suggest",
                        {"keyword": kw, "competitor_completions": n})


class RedditWTPScorer(SignalScorer):
    """Willingness-to-pay proxy from Reddit posts mentioning pricing."""

    dimension = "wtp"
    URL = "https://www.reddit.com/search.json?q={q}&limit=25"
    PRICE_WORDS = ("$", "price", "pricing", "paid", "subscription",
                   "per month", "/mo", "worth it", "pay for", "willing to pay")

    def __init__(self, fetch: Optional[JsonFetcher] = None):
        self._fetch = fetch or default_json_fetch

    async def score(self, idea: str) -> Optional[SubScore]:
        kw = core_keyword(idea)
        data = await self._fetch(self.URL.format(q=quote_plus(kw)))
        if not data:
            return None
        try:
            children = data["data"]["children"]
        except (KeyError, TypeError):
            return None
        if not children:
            return SubScore("wtp", 25, "reddit", {"posts": 0, "wtp_hits": 0})
        hits = 0
        for child in children:
            d = child.get("data", {})
            text = f"{d.get('title', '')} {d.get('selftext', '')}".lower()
            if any(w in text for w in self.PRICE_WORDS):
                hits += 1
        return SubScore("wtp", _clamp(25 + hits * 10), "reddit",
                        {"posts": len(children), "wtp_hits": hits})


class HeuristicICPScorer(SignalScorer):
    """ICP clarity from named-audience signals (no free API exists)."""

    dimension = "icp"

    async def score(self, idea: str) -> Optional[SubScore]:
        t = f" {idea.lower()} "
        value = 80 if any(a in t for a in AUDIENCE_TERMS) else 40
        return SubScore("icp", value, "heuristic", {})


def default_live_scorers(
    fetch: Optional[JsonFetcher] = None,
) -> Dict[str, SignalScorer]:
    """The standard set of live signal scorers keyed by dimension."""
    return {
        "demand": GoogleSuggestDemandScorer(fetch),
        "competitor": SuggestCompetitorScorer(fetch),
        "wtp": RedditWTPScorer(fetch),
        "icp": HeuristicICPScorer(),
    }
