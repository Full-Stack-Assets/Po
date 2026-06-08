"""
Action Tools — tools.py
=======================

Executable tools that agents can invoke to perform real actions.
Each tool returns a structured result that feeds into the verification layer.

Tools:
- ``EmailOutboundTool``  — send transactional/outreach email via Resend API
- ``ContentGeneratorTool`` — generate marketing/blog content via the LLM
- ``WebResearchTool``    — fetch and extract content from web pages
- ``DeployHealthCheckTool`` — verify a deployed URL is live
- ``LandingPageTool``    — generate + deploy a landing page

All tools follow a common ``Tool`` interface with ``execute()`` returning
a ``ToolResult``, and each declares ``verify_actions`` specs so the
verification layer can independently confirm the tool's side effects.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
import json
import logging
import time

logger = logging.getLogger(__name__)


@dataclass
class ToolResult:
    tool: str
    success: bool
    output: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    verify_actions: List[Dict[str, Any]] = field(default_factory=list)
    cost_usd: float = 0.0
    latency_ms: float = 0.0


class Tool(ABC):
    name: str = ""
    description: str = ""

    @abstractmethod
    async def execute(self, params: Dict[str, Any]) -> ToolResult:
        ...

    def spec(self) -> Dict[str, Any]:
        return {"name": self.name, "description": self.description}


class EmailOutboundTool(Tool):
    """Send email via Resend API (or any SMTP-compatible provider)."""

    name = "send_email"
    description = "Send a transactional or outreach email to a recipient."

    def __init__(self, api_key: Optional[str] = None,
                 sender: Optional[Callable] = None):
        import os
        self._api_key = api_key or os.environ.get("RESEND_API_KEY", "")
        self._sender = sender

    async def execute(self, params: Dict[str, Any]) -> ToolResult:
        to = params.get("to", "")
        subject = params.get("subject", "")
        body = params.get("body", "")
        from_addr = params.get("from", "noreply@po-operator.com")

        if not (to and subject and body):
            return ToolResult(self.name, False,
                              error="to, subject, and body are required")

        start = time.time()
        try:
            result = await self._send(to, from_addr, subject, body)
            latency = (time.time() - start) * 1000
            domain = to.split("@")[-1] if "@" in to else ""
            return ToolResult(
                tool=self.name, success=True,
                output=f"Email sent to {to}: {subject}",
                data={"message_id": result.get("id", ""), "to": to,
                      "subject": subject},
                verify_actions=[{"type": "email_deliverability",
                                 "domain": domain}] if domain else [],
                latency_ms=latency,
            )
        except Exception as e:
            return ToolResult(self.name, False, error=str(e),
                              latency_ms=(time.time() - start) * 1000)

    async def _send(self, to: str, from_addr: str,
                    subject: str, body: str) -> Dict[str, Any]:
        if self._sender:
            return await self._sender(to=to, from_addr=from_addr,
                                      subject=subject, body=body)
        if not self._api_key:
            raise RuntimeError("RESEND_API_KEY not set")
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {self._api_key}",
                         "Content-Type": "application/json"},
                json={"from": from_addr, "to": [to],
                      "subject": subject, "html": body},
            ) as resp:
                data = await resp.json()
                if resp.status >= 400:
                    raise RuntimeError(f"Resend API error {resp.status}: "
                                       f"{data}")
                return data


class ContentGeneratorTool(Tool):
    """Generate marketing content (blog posts, emails, landing copy) via LLM."""

    name = "generate_content"
    description = "Generate marketing content: blog posts, email copy, landing pages."

    def __init__(self, llm: Any = None):
        self._llm = llm

    async def execute(self, params: Dict[str, Any]) -> ToolResult:
        content_type = params.get("type", "blog_post")
        topic = params.get("topic", "")
        audience = params.get("audience", "B2B SaaS founders")
        tone = params.get("tone", "professional")
        length = params.get("length", "medium")

        if not topic:
            return ToolResult(self.name, False,
                              error="topic is required")
        if not self._llm:
            return ToolResult(self.name, False,
                              error="LLM not configured")

        from orchestrator_agent.llm_providers import Message

        length_guide = {"short": "200-400 words", "medium": "600-1000 words",
                        "long": "1500-2500 words"}.get(length, "600-1000 words")

        prompt = (
            f"Write a {content_type} about: {topic}\n\n"
            f"Target audience: {audience}\n"
            f"Tone: {tone}\n"
            f"Length: {length_guide}\n\n"
            f"Output the content directly, ready to publish."
        )

        start = time.time()
        try:
            resp = await self._llm.complete(
                messages=[
                    Message(role="system",
                            content="You are an expert content writer for B2B SaaS. "
                                    "Write compelling, actionable content."),
                    Message(role="user", content=prompt),
                ],
                capability="writing",
                temperature=0.7,
                max_tokens=4096,
            )
            latency = (time.time() - start) * 1000
            if resp.success:
                return ToolResult(
                    tool=self.name, success=True,
                    output=resp.content,
                    data={"type": content_type, "topic": topic,
                          "model": resp.model, "tokens": resp.usage.total_tokens},
                    cost_usd=resp.usage.total_cost,
                    latency_ms=latency,
                )
            return ToolResult(self.name, False, error=resp.error,
                              latency_ms=latency)
        except Exception as e:
            return ToolResult(self.name, False, error=str(e),
                              latency_ms=(time.time() - start) * 1000)


class WebResearchTool(Tool):
    """Fetch a URL and extract its text content for analysis."""

    name = "web_research"
    description = "Fetch and extract text content from a web page for analysis."

    def __init__(self, fetcher: Optional[Callable] = None):
        self._fetcher = fetcher

    async def execute(self, params: Dict[str, Any]) -> ToolResult:
        url = params.get("url", "")
        if not url:
            return ToolResult(self.name, False, error="url is required")

        start = time.time()
        try:
            status, body = await self._fetch(url)
            latency = (time.time() - start) * 1000

            if 200 <= status < 400:
                text = self._extract_text(body)
                return ToolResult(
                    tool=self.name, success=True,
                    output=text[:5000],
                    data={"url": url, "status": status,
                          "length": len(text)},
                    verify_actions=[{"type": "deploy_health", "url": url}],
                    latency_ms=latency,
                )
            return ToolResult(self.name, False,
                              error=f"HTTP {status}",
                              data={"url": url, "status": status},
                              latency_ms=latency)
        except Exception as e:
            return ToolResult(self.name, False, error=str(e),
                              latency_ms=(time.time() - start) * 1000)

    async def _fetch(self, url: str) -> tuple:
        if self._fetcher:
            return await self._fetcher(url)
        import aiohttp
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                return resp.status, await resp.text()

    @staticmethod
    def _extract_text(html: str) -> str:
        import re
        text = re.sub(r"<script[^>]*>.*?</script>", "", html,
                       flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text,
                       flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text


class DeployHealthCheckTool(Tool):
    """Check if a deployed URL is live and returning expected content."""

    name = "check_deploy"
    description = "Verify a deployed URL returns 200 and optionally contains expected text."

    def __init__(self, fetcher: Optional[Callable] = None):
        self._fetcher = fetcher

    async def execute(self, params: Dict[str, Any]) -> ToolResult:
        url = params.get("url", "")
        expect_text = params.get("expect_text")
        if not url:
            return ToolResult(self.name, False, error="url is required")

        start = time.time()
        try:
            status, body = await self._fetch(url)
            latency = (time.time() - start) * 1000
            ok = 200 <= status < 400
            if ok and expect_text:
                ok = expect_text in body
            return ToolResult(
                tool=self.name, success=ok,
                output=f"{'Live' if ok else 'Down'}: {url} (HTTP {status})",
                data={"url": url, "status": status,
                      "text_found": expect_text in body if expect_text else None},
                latency_ms=latency,
            )
        except Exception as e:
            return ToolResult(self.name, False, error=str(e),
                              latency_ms=(time.time() - start) * 1000)

    async def _fetch(self, url: str) -> tuple:
        if self._fetcher:
            return await self._fetcher(url)
        import aiohttp
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                return resp.status, await resp.text()


class LandingPageTool(Tool):
    """Generate a landing page and optionally deploy it."""

    name = "landing_page"
    description = "Generate a landing page from a product description and deploy it."

    def __init__(self, llm: Any = None, deployer: Optional[Callable] = None):
        self._llm = llm
        self._deployer = deployer

    async def execute(self, params: Dict[str, Any]) -> ToolResult:
        product = params.get("product", "")
        headline = params.get("headline", "")
        cta = params.get("cta", "Get Started")
        deploy_url = params.get("deploy_url")

        if not product:
            return ToolResult(self.name, False,
                              error="product description is required")
        if not self._llm:
            return ToolResult(self.name, False, error="LLM not configured")

        from orchestrator_agent.llm_providers import Message

        start = time.time()
        try:
            resp = await self._llm.complete(
                messages=[
                    Message(role="system",
                            content="You are an expert landing page designer. "
                                    "Generate a complete, single-file HTML landing page "
                                    "with inline CSS. Mobile-responsive, modern design. "
                                    "Output ONLY the HTML, no explanation."),
                    Message(role="user",
                            content=f"Product: {product}\n"
                                    f"Headline: {headline or 'auto-generate'}\n"
                                    f"CTA button text: {cta}\n"
                                    f"Include: hero section, features, social proof, "
                                    f"pricing hint, CTA, footer."),
                ],
                capability="writing",
                temperature=0.7,
                max_tokens=8192,
            )
            latency = (time.time() - start) * 1000

            if not resp.success:
                return ToolResult(self.name, False, error=resp.error,
                                  latency_ms=latency)

            result = ToolResult(
                tool=self.name, success=True,
                output=resp.content,
                data={"product": product, "model": resp.model,
                      "tokens": resp.usage.total_tokens},
                cost_usd=resp.usage.total_cost,
                latency_ms=latency,
            )

            if deploy_url and self._deployer:
                deploy_result = await self._deployer(resp.content, deploy_url)
                result.data["deployed"] = True
                result.data["deploy_url"] = deploy_result.get("url", deploy_url)
                result.verify_actions.append({
                    "type": "deploy_health",
                    "url": result.data["deploy_url"],
                })

            return result
        except Exception as e:
            return ToolResult(self.name, False, error=str(e),
                              latency_ms=(time.time() - start) * 1000)


class ToolRegistry:
    """Registry of available tools that agents can invoke."""

    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> "ToolRegistry":
        self._tools[tool.name] = tool
        return self

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def list_tools(self) -> List[Dict[str, Any]]:
        return [t.spec() for t in self._tools.values()]

    async def execute(self, name: str, params: Dict[str, Any]) -> ToolResult:
        tool = self._tools.get(name)
        if not tool:
            return ToolResult(tool=name, success=False,
                              error=f"Unknown tool: {name}")
        return await tool.execute(params)


def default_tool_registry(llm: Any = None) -> ToolRegistry:
    """Create a registry with all standard tools."""
    registry = ToolRegistry()
    registry.register(EmailOutboundTool())
    registry.register(ContentGeneratorTool(llm))
    registry.register(WebResearchTool())
    registry.register(DeployHealthCheckTool())
    registry.register(LandingPageTool(llm))
    return registry
