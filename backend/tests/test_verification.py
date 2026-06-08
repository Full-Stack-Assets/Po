"""Unit tests for the verification layer."""

import pytest

from orchestrator_agent.verification import VerificationLayer, VerificationResult


def test_extract_urls_dedupes_and_trims():
    text = ("See https://example.com/deploy. Also https://example.com/deploy "
            "and (https://foo.dev/page).")
    urls = VerificationLayer.extract_urls(text)
    assert urls == ["https://example.com/deploy", "https://foo.dev/page"]


def test_extract_urls_empty():
    assert VerificationLayer.extract_urls("no links here") == []


@pytest.mark.asyncio
async def test_verify_passes_on_200():
    async def fetcher(url):
        return 200

    layer = VerificationLayer(fetcher=fetcher)
    results = await layer.verify_output("deployed at https://example.com")
    assert len(results) == 1
    assert results[0].passed is True
    assert results[0].details["status"] == 200


@pytest.mark.asyncio
async def test_verify_fails_on_500():
    async def fetcher(url):
        return 500

    layer = VerificationLayer(fetcher=fetcher)
    results = await layer.verify_output("see https://example.com/broken")
    assert results[0].passed is False


@pytest.mark.asyncio
async def test_verify_handles_fetch_exception():
    async def fetcher(url):
        raise ConnectionError("dns failure")

    layer = VerificationLayer(fetcher=fetcher)
    results = await layer.verify_output("https://nope.invalid")
    assert results[0].passed is False
    assert "error" in results[0].details


@pytest.mark.asyncio
async def test_disabled_layer_returns_nothing():
    layer = VerificationLayer(enabled=False)
    assert await layer.verify_output("https://example.com") == []


def test_summarize():
    results = [
        VerificationResult("http_status", True),
        VerificationResult("http_status", False),
    ]
    summary = VerificationLayer.summarize(results)
    assert summary == {"checked": 2, "passed": 1, "failed": 1,
                       "all_passed": False}
    assert VerificationLayer.summarize([])["all_passed"] is False
