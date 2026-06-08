"""
Validation Gate — validation.py
================================

Po's first differentiator: never spend on an unvalidated idea.

Before an idea/workflow is executed, the gate produces a demand-validation
score across four dimensions (demand, competitor density, ICP clarity,
willingness-to-pay) and a red / yellow / green rating. A RED rating is
*blocking* — execution is refused unless the caller explicitly overrides.

Scoring backends
----------------
- **LLM-backed** (preferred): if an ``LLMManager`` is supplied, the gate asks a
  cheap classification-capable model to score the idea and return JSON.
- **Heuristic** (offline fallback): a deterministic signal-based scorer used
  when no LLM is available or the LLM call fails. This keeps the gate usable
  (and unit-testable) without network access.

Both are placeholders for real demand signals (keyword volume, competitor
scraping, Reddit/X WTP mining) — wiring those tools in only changes the
scorers, not the gate's contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional
import asyncio
import json
import logging
import re

from orchestrator_agent.llm_providers import Message

logger = logging.getLogger(__name__)


class ValidationScore(Enum):
    RED = "red"        # blocking — do not spend without override
    YELLOW = "yellow"  # proceed with caution
    GREEN = "green"    # validated — safe to proceed


@dataclass
class ValidationResult:
    """Outcome of a demand-validation check on an idea."""
    idea: str
    overall_score: int                 # 0-100 weighted composite
    score: ValidationScore
    demand_score: int = 0
    competitor_score: int = 0
    icp_score: int = 0
    wtp_score: int = 0
    rationale: str = ""
    override_required: bool = False
    backend: str = "heuristic"         # "llm" | "heuristic"
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_blocking(self) -> bool:
        return self.score == ValidationScore.RED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "idea": self.idea,
            "overall_score": self.overall_score,
            "score": self.score.value,
            "demand_score": self.demand_score,
            "competitor_score": self.competitor_score,
            "icp_score": self.icp_score,
            "wtp_score": self.wtp_score,
            "rationale": self.rationale,
            "override_required": self.override_required,
            "backend": self.backend,
            "details": self.details,
        }


class ValidationGate:
    """Scores an idea and assigns a red/yellow/green rating."""

    DEFAULT_WEIGHTS = {
        "demand": 0.30,
        "competitor": 0.20,
        "icp": 0.25,
        "wtp": 0.25,
    }

    def __init__(
        self,
        llm: Optional[Any] = None,
        *,
        green_threshold: int = 70,
        red_threshold: int = 40,
        weights: Optional[Dict[str, float]] = None,
        scorers: Optional[Dict[str, Any]] = None,
    ):
        self.llm = llm
        self.green_threshold = green_threshold
        self.red_threshold = red_threshold
        self.weights = weights or dict(self.DEFAULT_WEIGHTS)
        # Optional pluggable per-dimension signal scorers (see signals.py).
        self.scorers = scorers

    @classmethod
    def with_live_signals(
        cls,
        llm: Optional[Any] = None,
        fetch: Optional[Any] = None,
        **kwargs: Any,
    ) -> "ValidationGate":
        """Build a gate backed by live network signal scorers."""
        from orchestrator_agent.signals import default_live_scorers
        return cls(llm=llm, scorers=default_live_scorers(fetch), **kwargs)

    async def validate(self, idea: str) -> ValidationResult:
        details: Dict[str, Any] = {"weights": self.weights}
        if self.scorers:
            scores, sources = await self._composite_scores(idea)
            backend = "composite"
            details["sources"] = sources
        elif self.llm is not None:
            scores = await self._llm_scores(idea)
            if scores is not None:
                backend = "llm"
            else:
                scores, backend = self._heuristic_scores(idea), "heuristic"
        else:
            scores, backend = self._heuristic_scores(idea), "heuristic"

        details["raw_scores"] = scores
        overall = round(sum(scores[k] * self.weights[k] for k in self.weights))
        rating = self._rate(overall)
        return ValidationResult(
            idea=idea,
            overall_score=overall,
            score=rating,
            demand_score=scores["demand"],
            competitor_score=scores["competitor"],
            icp_score=scores["icp"],
            wtp_score=scores["wtp"],
            rationale=self._rationale(rating, overall),
            override_required=(rating == ValidationScore.RED),
            backend=backend,
            details=details,
        )

    async def _composite_scores(self, idea: str):
        """Run each pluggable scorer; fall back to heuristic per dimension."""
        heur = self._heuristic_scores(idea)
        scores: Dict[str, int] = {}
        sources: Dict[str, str] = {}

        async def run(dim: str):
            scorer = self.scorers.get(dim)
            if scorer is None:
                scores[dim], sources[dim] = heur[dim], "heuristic"
                return
            try:
                sub = await scorer.score(idea)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"scorer '{dim}' failed: {e}")
                sub = None
            if sub is None:
                scores[dim], sources[dim] = heur[dim], "heuristic(fallback)"
            else:
                scores[dim], sources[dim] = sub.value, sub.source

        await asyncio.gather(*(run(d) for d in
                               ("demand", "competitor", "icp", "wtp")))
        return scores, sources

    def _rate(self, overall: int) -> ValidationScore:
        if overall >= self.green_threshold:
            return ValidationScore.GREEN
        if overall < self.red_threshold:
            return ValidationScore.RED
        return ValidationScore.YELLOW

    @staticmethod
    def _rationale(rating: ValidationScore, overall: int) -> str:
        if rating == ValidationScore.GREEN:
            return f"Validated ({overall}/100): clear demand and reachable ICP."
        if rating == ValidationScore.YELLOW:
            return (f"Mixed signals ({overall}/100): proceed cautiously and "
                    f"tighten the scope before committing spend.")
        return (f"Weak signals ({overall}/100): no clear demand or buyer. "
                f"Override required to execute anyway.")

    # ── Heuristic backend (offline, deterministic) ─────────────────────

    _CROWDED = ("app", "ai", "chatbot", "social network", "crm", "todo",
                "to-do", "note app", "platform")
    _AUDIENCE = ("for ", "founders", "teams", "developers", "marketers",
                 "agencies", "b2b", "smb", "saas", "ecommerce")
    _WTP = ("$", "paid", "subscription", "pricing", "b2b", "enterprise",
            "saas", "revenue", "budget", "per month", "/mo")

    def _heuristic_scores(self, idea: str) -> Dict[str, int]:
        t = f" {idea.lower().strip()} "
        unique_words = len(set(t.split()))

        # Empty or one-word "ideas" have no demand signal at all -> uniformly
        # low so they rate RED (blocking) rather than coasting on defaults.
        if unique_words <= 1:
            return {"demand": 10, "competitor": 10, "icp": 10, "wtp": 10}

        # Demand: specific, fleshed-out ideas score higher than vague ones.
        demand = min(100, 25 + unique_words * 4)

        # Competitor density: penalize generic/crowded category words.
        competitor = 85 - 12 * sum(1 for c in self._CROWDED if c in t)
        competitor = max(10, competitor)

        # ICP clarity: bonus when a target audience is named.
        icp = 80 if any(a in t for a in self._AUDIENCE) else 40

        # Willingness-to-pay: bonus for monetization signals.
        wtp = 75 if any(w in t for w in self._WTP) else 40

        return {
            "demand": int(demand),
            "competitor": int(competitor),
            "icp": int(icp),
            "wtp": int(wtp),
        }

    # ── LLM backend ────────────────────────────────────────────────────

    _JSON_RE = re.compile(r"\{.*\}", re.DOTALL)

    async def _llm_scores(self, idea: str) -> Optional[Dict[str, int]]:
        try:
            resp = await self.llm.complete(
                messages=[
                    Message(role="system", content=(
                        "You are a demand-validation analyst. Score a startup "
                        "idea from 0-100 on four dimensions and respond with "
                        "ONLY a JSON object with integer keys: "
                        '"demand" (search/market demand), '
                        '"competitor" (higher = less saturated / more room), '
                        '"icp" (clarity & reachability of the ideal customer), '
                        '"wtp" (willingness to pay). No prose.'
                    )),
                    Message(role="user", content=idea),
                ],
                capability="classification",
                temperature=0.0,
                max_tokens=120,
            )
            if not resp.success:
                return None
            m = self._JSON_RE.search(resp.content or "")
            if not m:
                return None
            data = json.loads(m.group(0))
            return {
                k: max(0, min(100, int(data.get(k, 0))))
                for k in ("demand", "competitor", "icp", "wtp")
            }
        except Exception as e:  # noqa: BLE001 — fall back to heuristic
            logger.warning(f"ValidationGate LLM scoring failed: {e}")
            return None
