"""Tests for the OpenRouter provider."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from orchestrator_agent.llm_providers import (
    OpenRouterProvider, ProviderConfig, ProviderType, Message,
)


def _config(**overrides):
    defaults = dict(
        provider_type=ProviderType.OPENROUTER,
        api_key="sk-or-test-key",
        default_model="openai/gpt-4.1-mini",
        extra={"referer": "https://example.com", "title": "Test"},
    )
    defaults.update(overrides)
    return ProviderConfig(**defaults)


class TestOpenRouterProvider:

    def test_extra_headers(self):
        provider = OpenRouterProvider(_config())
        headers = provider._extra_headers()
        assert headers["HTTP-Referer"] == "https://example.com"
        assert headers["X-OpenRouter-Title"] == "Test"

    def test_extra_headers_empty(self):
        provider = OpenRouterProvider(_config(extra={}))
        headers = provider._extra_headers()
        assert "HTTP-Referer" not in headers

    def test_available_models(self):
        provider = OpenRouterProvider(_config())
        models = provider.get_available_models()
        assert len(models) >= 4
        names = [m.model_id for m in models]
        assert "openai/gpt-4.1-mini" in names
        assert "anthropic/claude-sonnet-4-5" in names
        for m in models:
            assert m.provider == ProviderType.OPENROUTER

    @pytest.mark.asyncio
    async def test_complete_success(self):
        provider = OpenRouterProvider(_config())
        mock_usage = MagicMock(prompt_tokens=10, completion_tokens=20)
        mock_choice = MagicMock()
        mock_choice.message.content = "Hello from OpenRouter"
        mock_choice.finish_reason = "stop"
        mock_resp = MagicMock(choices=[mock_choice], usage=mock_usage)

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)
        provider._client = mock_client

        resp = await provider.complete(
            [Message(role="user", content="Hi")],
            model="openai/gpt-4.1-mini",
        )
        assert resp.success
        assert resp.content == "Hello from OpenRouter"
        assert resp.provider == ProviderType.OPENROUTER

    @pytest.mark.asyncio
    async def test_complete_omits_null_stop(self):
        provider = OpenRouterProvider(_config())
        mock_usage = MagicMock(prompt_tokens=5, completion_tokens=10)
        mock_choice = MagicMock()
        mock_choice.message.content = "ok"
        mock_choice.finish_reason = "stop"
        mock_resp = MagicMock(choices=[mock_choice], usage=mock_usage)

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)
        provider._client = mock_client

        await provider.complete(
            [Message(role="user", content="test")], stop=None
        )
        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert "stop" not in call_kwargs

    @pytest.mark.asyncio
    async def test_complete_error(self):
        provider = OpenRouterProvider(_config())
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=RuntimeError("API down")
        )
        provider._client = mock_client

        resp = await provider.complete(
            [Message(role="user", content="test")]
        )
        assert not resp.success
        assert "API down" in resp.error

    def test_provider_in_map(self):
        from orchestrator_agent.llm_providers import PROVIDER_MAP
        assert ProviderType.OPENROUTER in PROVIDER_MAP

    def test_create_provider(self):
        from orchestrator_agent.llm_providers import create_provider
        provider = create_provider(_config())
        assert isinstance(provider, OpenRouterProvider)
