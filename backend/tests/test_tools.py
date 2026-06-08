"""Tests for the action tools layer (tools.py)."""
import pytest
from orchestrator_agent.tools import (
    ToolResult, ToolRegistry, EmailOutboundTool, ContentGeneratorTool,
    WebResearchTool, DeployHealthCheckTool, LandingPageTool,
    default_tool_registry,
)


# ── Helpers ──────────────────────────────────────────────────────────

class FakeLLM:
    async def complete(self, messages, capability="", temperature=0.7,
                       max_tokens=4096):
        from types import SimpleNamespace
        return SimpleNamespace(
            success=True,
            content="Generated content about test topic.",
            model="fake-model",
            error=None,
            usage=SimpleNamespace(total_tokens=100, total_cost=0.001),
        )


async def fake_email_sender(to, from_addr, subject, body):
    return {"id": "msg_fake123"}


async def fake_fetcher(url):
    if "error" in url:
        raise ConnectionError("network down")
    return (200, "<html><body><h1>Hello World</h1><p>Test content</p></body></html>")


async def fake_fetcher_404(url):
    return (404, "Not Found")


# ── ToolResult ───────────────────────────────────────────────────────

def test_tool_result_defaults():
    r = ToolResult(tool="test", success=True)
    assert r.output == ""
    assert r.data == {}
    assert r.verify_actions == []


# ── EmailOutboundTool ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_email_send_success():
    tool = EmailOutboundTool(sender=fake_email_sender)
    result = await tool.execute({
        "to": "user@example.com",
        "subject": "Test Subject",
        "body": "<p>Hello</p>",
    })
    assert result.success
    assert "user@example.com" in result.output
    assert result.data["message_id"] == "msg_fake123"
    assert len(result.verify_actions) == 1
    assert result.verify_actions[0]["type"] == "email_deliverability"
    assert result.verify_actions[0]["domain"] == "example.com"


@pytest.mark.asyncio
async def test_email_missing_fields():
    tool = EmailOutboundTool(sender=fake_email_sender)
    result = await tool.execute({"to": "user@example.com"})
    assert not result.success
    assert "required" in result.error


@pytest.mark.asyncio
async def test_email_no_api_key():
    tool = EmailOutboundTool(api_key="")
    result = await tool.execute({
        "to": "user@example.com",
        "subject": "Test",
        "body": "Hello",
    })
    assert not result.success
    assert "RESEND_API_KEY" in result.error


# ── ContentGeneratorTool ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_content_generator_success():
    tool = ContentGeneratorTool(llm=FakeLLM())
    result = await tool.execute({
        "topic": "AI growth strategies",
        "type": "blog_post",
    })
    assert result.success
    assert "Generated content" in result.output
    assert result.data["type"] == "blog_post"
    assert result.cost_usd > 0


@pytest.mark.asyncio
async def test_content_generator_no_topic():
    tool = ContentGeneratorTool(llm=FakeLLM())
    result = await tool.execute({})
    assert not result.success
    assert "topic" in result.error


@pytest.mark.asyncio
async def test_content_generator_no_llm():
    tool = ContentGeneratorTool()
    result = await tool.execute({"topic": "test"})
    assert not result.success
    assert "LLM" in result.error


# ── WebResearchTool ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_web_research_success():
    tool = WebResearchTool(fetcher=fake_fetcher)
    result = await tool.execute({"url": "https://example.com"})
    assert result.success
    assert "Hello World" in result.output
    assert result.data["status"] == 200
    assert result.verify_actions[0]["type"] == "deploy_health"


@pytest.mark.asyncio
async def test_web_research_no_url():
    tool = WebResearchTool(fetcher=fake_fetcher)
    result = await tool.execute({})
    assert not result.success


@pytest.mark.asyncio
async def test_web_research_error():
    tool = WebResearchTool(fetcher=fake_fetcher)
    result = await tool.execute({"url": "https://error.com"})
    assert not result.success
    assert "network down" in result.error


@pytest.mark.asyncio
async def test_web_research_404():
    tool = WebResearchTool(fetcher=fake_fetcher_404)
    result = await tool.execute({"url": "https://example.com/missing"})
    assert not result.success
    assert "404" in result.error


# ── DeployHealthCheckTool ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_deploy_check_success():
    tool = DeployHealthCheckTool(fetcher=fake_fetcher)
    result = await tool.execute({"url": "https://example.com"})
    assert result.success
    assert "Live" in result.output


@pytest.mark.asyncio
async def test_deploy_check_with_text():
    tool = DeployHealthCheckTool(fetcher=fake_fetcher)
    result = await tool.execute({
        "url": "https://example.com",
        "expect_text": "Hello World",
    })
    assert result.success

    result2 = await tool.execute({
        "url": "https://example.com",
        "expect_text": "Not Here",
    })
    assert not result2.success


@pytest.mark.asyncio
async def test_deploy_check_no_url():
    tool = DeployHealthCheckTool(fetcher=fake_fetcher)
    result = await tool.execute({})
    assert not result.success


# ── LandingPageTool ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_landing_page_success():
    tool = LandingPageTool(llm=FakeLLM())
    result = await tool.execute({"product": "AI SaaS for founders"})
    assert result.success
    assert result.cost_usd > 0


@pytest.mark.asyncio
async def test_landing_page_no_product():
    tool = LandingPageTool(llm=FakeLLM())
    result = await tool.execute({})
    assert not result.success


@pytest.mark.asyncio
async def test_landing_page_with_deploy():
    deployed = {}

    async def fake_deployer(html, url):
        deployed["html"] = html
        return {"url": url}

    tool = LandingPageTool(llm=FakeLLM(), deployer=fake_deployer)
    result = await tool.execute({
        "product": "AI SaaS",
        "deploy_url": "https://my-site.vercel.app",
    })
    assert result.success
    assert result.data.get("deployed")
    assert result.verify_actions[0]["type"] == "deploy_health"
    assert deployed["html"]


# ── ToolRegistry ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_registry_execute_unknown():
    reg = ToolRegistry()
    result = await reg.execute("nonexistent", {})
    assert not result.success
    assert "Unknown" in result.error


@pytest.mark.asyncio
async def test_registry_list_and_execute():
    reg = ToolRegistry()
    reg.register(DeployHealthCheckTool(fetcher=fake_fetcher))
    tools = reg.list_tools()
    assert len(tools) == 1
    assert tools[0]["name"] == "check_deploy"

    result = await reg.execute("check_deploy", {"url": "https://example.com"})
    assert result.success


def test_default_tool_registry():
    reg = default_tool_registry(FakeLLM())
    tools = reg.list_tools()
    names = {t["name"] for t in tools}
    assert names == {"send_email", "generate_content", "web_research",
                     "check_deploy", "landing_page"}
