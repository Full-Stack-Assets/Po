"""
Side-effecting verifiers — verifiers.py
=======================================

Concrete, deterministic checkers that prove a real action actually worked.
Each implements the :class:`Verifier` interface and is keyed by ``checker_type``
so the :class:`~orchestrator_agent.verification.VerificationLayer` can route an
action spec (``{"type": ..., ...}``) to the right checker.

Shipped verifiers:

- ``deploy_health`` — HTTP GET a deployed URL; pass on the expected status and
  (optionally) an expected substring in the body.
- ``email_deliverability`` — confirm a sending domain publishes SPF + DMARC
  (and DKIM when a selector is given) via DNS TXT lookups.
- ``stripe_webhook`` — verify a Stripe webhook signature (HMAC-SHA256 over
  ``"{t}.{payload}"``) so we only trust events Stripe actually signed.

Every external dependency (HTTP fetch, DNS resolver) is injectable, so all
verifiers are unit-testable offline.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable, Dict, List, Optional
import hashlib
import hmac
import logging
import time

from orchestrator_agent.verification import VerificationResult

logger = logging.getLogger(__name__)

# (status_code, body_text)
HttpFetcher = Callable[[str], Awaitable[tuple]]
# domain/name, record_type -> list of TXT strings
DnsResolver = Callable[[str, str], Awaitable[List[str]]]


class Verifier(ABC):
    checker_type: str = ""

    @abstractmethod
    async def verify(self, spec: Dict[str, Any]) -> VerificationResult:
        ...


class HttpDeployVerifier(Verifier):
    """Verifies a deployed URL is live (status + optional body substring)."""

    checker_type = "deploy_health"

    def __init__(self, fetcher: Optional[HttpFetcher] = None,
                 *, timeout_seconds: int = 10):
        self._fetcher = fetcher
        self.timeout_seconds = timeout_seconds

    async def verify(self, spec: Dict[str, Any]) -> VerificationResult:
        url = spec.get("url", "")
        expect_status = spec.get("expect_status", 200)
        expect_substring = spec.get("expect_substring")
        if not url:
            return VerificationResult(self.checker_type, False,
                                      details={"error": "no url in spec"})
        try:
            status, body = await self._fetch(url)
        except Exception as e:  # noqa: BLE001
            return VerificationResult(self.checker_type, False, url,
                                      {"error": str(e)})
        ok = status == expect_status
        details: Dict[str, Any] = {"status": status,
                                   "expected_status": expect_status}
        if ok and expect_substring is not None:
            ok = expect_substring in (body or "")
            details["substring_found"] = ok
            details["expect_substring"] = expect_substring
        return VerificationResult(self.checker_type, ok, url, details)

    async def _fetch(self, url: str) -> tuple:
        if self._fetcher is not None:
            return await self._fetcher(url)
        import aiohttp
        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                return resp.status, await resp.text()


class EmailDeliverabilityVerifier(Verifier):
    """Confirms a sending domain publishes SPF + DMARC (+ DKIM if selector)."""

    checker_type = "email_deliverability"

    def __init__(self, resolver: Optional[DnsResolver] = None):
        self._resolver = resolver

    async def verify(self, spec: Dict[str, Any]) -> VerificationResult:
        domain = spec.get("domain", "")
        selector = spec.get("selector")
        if not domain:
            return VerificationResult(self.checker_type, False,
                                      details={"error": "no domain in spec"})
        try:
            spf = await self._has_record(domain, "v=spf1")
            dmarc = await self._has_record(f"_dmarc.{domain}", "v=DMARC1")
            dkim = None
            if selector:
                dkim = await self._has_record(
                    f"{selector}._domainkey.{domain}", "v=DKIM1")
        except Exception as e:  # noqa: BLE001
            return VerificationResult(self.checker_type, False, domain,
                                      {"error": str(e)})
        passed = spf and dmarc and (dkim is not False)
        return VerificationResult(
            self.checker_type, passed, domain,
            {"spf": spf, "dmarc": dmarc, "dkim": dkim},
        )

    async def _has_record(self, name: str, marker: str) -> bool:
        records = await self._txt(name)
        return any(marker.lower() in r.lower() for r in records)

    async def _txt(self, name: str) -> List[str]:
        if self._resolver is not None:
            return await self._resolver(name, "TXT")
        try:
            import dns.asyncresolver
            answers = await dns.asyncresolver.resolve(name, "TXT")
            return [b"".join(r.strings).decode("utf-8", "ignore")
                    for r in answers]
        except Exception as e:  # noqa: BLE001
            logger.debug(f"DNS TXT lookup failed for {name}: {e}")
            return []


class StripeWebhookVerifier(Verifier):
    """Verifies a Stripe webhook signature (HMAC-SHA256, t.payload)."""

    checker_type = "stripe_webhook"

    async def verify(self, spec: Dict[str, Any]) -> VerificationResult:
        payload = spec.get("payload", "")
        sig_header = spec.get("signature", "")
        secret = spec.get("secret", "")
        tolerance = spec.get("tolerance")  # seconds, optional
        if not (payload and sig_header and secret):
            return VerificationResult(
                self.checker_type, False,
                details={"error": "payload, signature and secret required"})

        parts = dict(
            p.split("=", 1) for p in sig_header.split(",") if "=" in p
        )
        timestamp = parts.get("t", "")
        provided = parts.get("v1", "")
        if not (timestamp and provided):
            return VerificationResult(self.checker_type, False,
                                      details={"error": "malformed signature"})

        signed_payload = f"{timestamp}.{payload}".encode("utf-8")
        expected = hmac.new(secret.encode("utf-8"), signed_payload,
                            hashlib.sha256).hexdigest()
        match = hmac.compare_digest(expected, provided)

        details: Dict[str, Any] = {"signature_valid": match}
        if match and tolerance is not None:
            try:
                age = abs(time.time() - int(timestamp))
                details["age_seconds"] = round(age)
                if age > tolerance:
                    return VerificationResult(self.checker_type, False,
                                              details={**details,
                                                       "error": "stale"})
            except ValueError:
                return VerificationResult(self.checker_type, False,
                                          {"error": "bad timestamp"})
        return VerificationResult(self.checker_type, match, details=details)


def default_verifiers(
    http_fetcher: Optional[HttpFetcher] = None,
    dns_resolver: Optional[DnsResolver] = None,
) -> Dict[str, Verifier]:
    """The standard verifier set keyed by checker_type."""
    return {
        HttpDeployVerifier.checker_type: HttpDeployVerifier(http_fetcher),
        EmailDeliverabilityVerifier.checker_type:
            EmailDeliverabilityVerifier(dns_resolver),
        StripeWebhookVerifier.checker_type: StripeWebhookVerifier(),
    }
