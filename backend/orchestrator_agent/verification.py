"""
Verification Layer — verification.py
====================================

Po's core differentiator: prove the work actually worked.

After an agent acts, the verification layer independently checks the result
rather than trusting the agent's own "done". This module ships an HTTP
reachability checker that extracts URLs from an agent's output and confirms
each returns a success status — the building block for "deployed URL returns
200 and renders".

Checks are intentionally *deterministic* (a real HTTP request), not another
LLM judgment call, to avoid the "who verifies the verifier" problem. The
fetcher is injectable so checks can be unit-tested offline and so a richer
client (rendering, content assertions) can be swapped in later.

``fail_on_unverified`` controls policy: when True, a failed verification flips
the result to unsuccessful and signals the pipeline to refund the action's
budget. It defaults to False so that merely *citing* an unreachable URL in,
say, a research summary is recorded honestly without nuking the whole task —
teams flip it on for genuinely side-effecting actions (deploy, send, publish).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional
import logging
import re

logger = logging.getLogger(__name__)

# URLs, trimmed of common trailing punctuation/brackets.
_URL_RE = re.compile(r"https?://[^\s)\]}\"'>]+")


@dataclass
class VerificationResult:
    """Outcome of a single verification check."""
    checker_type: str
    passed: bool
    target: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "checker_type": self.checker_type,
            "passed": self.passed,
            "target": self.target,
            "details": self.details,
        }


class VerificationLayer:
    """Independently verifies claims found in an agent's output."""

    def __init__(
        self,
        fetcher: Optional[Callable[[str], Awaitable[int]]] = None,
        *,
        enabled: bool = True,
        fail_on_unverified: bool = False,
        timeout_seconds: int = 10,
    ):
        self._fetcher = fetcher
        self.enabled = enabled
        self.fail_on_unverified = fail_on_unverified
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def extract_urls(text: str) -> List[str]:
        """Return de-duplicated URLs (trailing punctuation stripped)."""
        found = (_URL_RE.findall(text or ""))
        cleaned = [u.rstrip(".,;:!?") for u in found]
        return list(dict.fromkeys(cleaned))

    async def verify_output(self, output: str) -> List[VerificationResult]:
        if not self.enabled:
            return []
        results: List[VerificationResult] = []
        for url in self.extract_urls(output):
            results.append(await self._check_url(url))
        return results

    async def _check_url(self, url: str) -> VerificationResult:
        try:
            status = await self._fetch(url)
            ok = 200 <= status < 400
            return VerificationResult(
                checker_type="http_status",
                passed=ok,
                target=url,
                details={"status": status},
            )
        except Exception as e:  # noqa: BLE001
            return VerificationResult(
                checker_type="http_status",
                passed=False,
                target=url,
                details={"error": str(e)},
            )

    async def _fetch(self, url: str) -> int:
        if self._fetcher is not None:
            return await self._fetcher(url)
        import aiohttp
        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                return resp.status

    @staticmethod
    def summarize(results: List[VerificationResult]) -> Dict[str, Any]:
        passed = sum(1 for r in results if r.passed)
        total = len(results)
        return {
            "checked": total,
            "passed": passed,
            "failed": total - passed,
            "all_passed": total > 0 and passed == total,
        }
