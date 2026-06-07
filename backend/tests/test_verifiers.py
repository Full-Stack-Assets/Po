"""Unit tests for side-effecting verifiers."""

import hashlib
import hmac
import time

import pytest

from orchestrator_agent.verifiers import (
    HttpDeployVerifier, EmailDeliverabilityVerifier, StripeWebhookVerifier,
    default_verifiers,
)
from orchestrator_agent.verification import VerificationLayer


# ── Deploy health ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_deploy_verifier_passes_on_status_and_substring():
    async def fetch(url):
        return 200, "<h1>Welcome to Po</h1>"

    v = HttpDeployVerifier(fetch)
    res = await v.verify({"url": "https://po.app", "expect_status": 200,
                          "expect_substring": "Welcome to Po"})
    assert res.passed is True
    assert res.details["substring_found"] is True


@pytest.mark.asyncio
async def test_deploy_verifier_fails_on_missing_substring():
    async def fetch(url):
        return 200, "error page"

    res = await HttpDeployVerifier(fetch).verify(
        {"url": "https://po.app", "expect_substring": "Welcome"})
    assert res.passed is False


@pytest.mark.asyncio
async def test_deploy_verifier_fails_on_wrong_status():
    async def fetch(url):
        return 502, ""

    res = await HttpDeployVerifier(fetch).verify({"url": "https://po.app"})
    assert res.passed is False
    assert res.details["status"] == 502


# ── Email deliverability ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_email_verifier_passes_with_spf_and_dmarc():
    async def resolver(name, rtype):
        if name == "po.app":
            return ["v=spf1 include:_spf.google.com ~all"]
        if name == "_dmarc.po.app":
            return ["v=DMARC1; p=reject"]
        return []

    res = await EmailDeliverabilityVerifier(resolver).verify(
        {"domain": "po.app"})
    assert res.passed is True
    assert res.details["spf"] is True
    assert res.details["dmarc"] is True


@pytest.mark.asyncio
async def test_email_verifier_fails_without_dmarc():
    async def resolver(name, rtype):
        if name == "po.app":
            return ["v=spf1 ~all"]
        return []

    res = await EmailDeliverabilityVerifier(resolver).verify(
        {"domain": "po.app"})
    assert res.passed is False


@pytest.mark.asyncio
async def test_email_verifier_checks_dkim_when_selector_given():
    async def resolver(name, rtype):
        return {
            "po.app": ["v=spf1 ~all"],
            "_dmarc.po.app": ["v=DMARC1; p=none"],
            "k1._domainkey.po.app": ["v=DKIM1; k=rsa; p=MIGf..."],
        }.get(name, [])

    res = await EmailDeliverabilityVerifier(resolver).verify(
        {"domain": "po.app", "selector": "k1"})
    assert res.passed is True
    assert res.details["dkim"] is True


# ── Stripe webhook ─────────────────────────────────────────────────────

def _stripe_sig(payload: str, secret: str, ts: int) -> str:
    signed = f"{ts}.{payload}".encode()
    v1 = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={ts},v1={v1}"


@pytest.mark.asyncio
async def test_stripe_verifier_accepts_valid_signature():
    payload = '{"id":"evt_1","type":"checkout.session.completed"}'
    secret = "whsec_test"
    ts = int(time.time())
    res = await StripeWebhookVerifier().verify({
        "payload": payload, "secret": secret,
        "signature": _stripe_sig(payload, secret, ts),
    })
    assert res.passed is True


@pytest.mark.asyncio
async def test_stripe_verifier_rejects_tampered_payload():
    payload = '{"id":"evt_1"}'
    secret = "whsec_test"
    ts = int(time.time())
    sig = _stripe_sig(payload, secret, ts)
    res = await StripeWebhookVerifier().verify({
        "payload": '{"id":"evt_TAMPERED"}', "secret": secret, "signature": sig,
    })
    assert res.passed is False


@pytest.mark.asyncio
async def test_stripe_verifier_rejects_stale_with_tolerance():
    payload = "{}"
    secret = "whsec_test"
    old_ts = int(time.time()) - 9999
    res = await StripeWebhookVerifier().verify({
        "payload": payload, "secret": secret,
        "signature": _stripe_sig(payload, secret, old_ts),
        "tolerance": 300,
    })
    assert res.passed is False
    assert res.details["error"] == "stale"


# ── Routing through the verification layer ─────────────────────────────

@pytest.mark.asyncio
async def test_layer_routes_action_specs_to_verifiers():
    async def fetch(url):
        return 200, "ok"

    layer = VerificationLayer()
    layer.register(HttpDeployVerifier(fetch))
    results = await layer.verify_actions([
        {"type": "deploy_health", "url": "https://po.app"},
        {"type": "nonexistent"},
    ])
    assert results[0].passed is True
    assert results[1].passed is False
    assert "no verifier" in results[1].details["error"]


def test_default_verifiers_registry_has_all_three():
    reg = default_verifiers()
    assert set(reg) == {"deploy_health", "email_deliverability",
                        "stripe_webhook"}
