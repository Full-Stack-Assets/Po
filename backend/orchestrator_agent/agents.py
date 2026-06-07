"""
Sub-Agents with Live LLM Integration
Each agent uses the LLMManager for real completions with specialized
system prompts, constraint-aware model selection, and automatic fallback.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
import time
import logging
import uuid

from orchestrator_agent.models import (
    Task, TaskContext, TaskStatus, AgentResult, AgentProfile, AgentCapability,
)
from orchestrator_agent.llm_providers import Message, LLMResponse
from orchestrator_agent.llm_manager import LLMManager

logger = logging.getLogger(__name__)


class SubAgent(ABC):
    """Abstract base class — wired to the LLMManager."""

    def __init__(self, llm: LLMManager, agent_id: str = "", name: str = ""):
        self.llm = llm
        self.agent_id = agent_id or str(uuid.uuid4())[:8]
        self.name = name or self.__class__.__name__

    @abstractmethod
    def get_profile(self) -> AgentProfile: ...

    @abstractmethod
    def get_system_prompt(self) -> str: ...

    async def execute(self, task: Task, context: TaskContext) -> AgentResult:
        start = time.time()
        profile = self.get_profile()
        logger.info(f"[{self.name}] Executing task {task.task_id} "
                     f"(intent={task.intent})")

        system_prompt = self.get_system_prompt()
        messages = context.to_messages(system_prompt)
        messages.append(Message(role="user", content=task.input_text))

        response: LLMResponse = await self.llm.complete(
            messages=messages,
            capability=profile.preferred_capability,
            temperature=self._get_temperature(task),
            max_tokens=self._get_max_tokens(task),
        )

        latency = (time.time() - start) * 1000

        if response.success:
            context.add_message("assistant", response.content, self.agent_id)
            return AgentResult(
                agent_id=self.agent_id, task_id=task.task_id,
                output=response.content, success=True,
                tokens_used=response.usage.total_tokens,
                cost=response.usage.total_cost, latency_ms=latency,
                model_used=response.model,
                provider_used=response.provider.value,
            )
        else:
            logger.error(f"[{self.name}] LLM call failed: {response.error}")
            return AgentResult(
                agent_id=self.agent_id, task_id=task.task_id,
                output="", success=False, error=response.error,
                latency_ms=latency, model_used=response.model,
                provider_used=response.provider.value,
            )

    def _get_temperature(self, task: Task) -> float:
        return 0.7

    def _get_max_tokens(self, task: Task) -> int:
        return 4096


class ResearchAgent(SubAgent):
    """Agent specialized in information gathering and research."""

    def __init__(self, llm: LLMManager):
        super().__init__(llm, name="ResearchAgent")

    def get_profile(self) -> AgentProfile:
        return AgentProfile(
            agent_id=self.agent_id, name=self.name,
            capabilities=[AgentCapability.RESEARCH,
                          AgentCapability.SUMMARIZATION],
            supported_intents=["research", "lookup", "find", "search",
                               "summarize", "investigate", "discover"],
            cost_per_1k_tokens=0.03, avg_latency_ms=2500, priority=1,
            preferred_capability="research",
        )

    def get_system_prompt(self) -> str:
        return (
            "You are a senior research analyst. Your role is to:\n"
            "1. Gather, synthesize, and present information accurately.\n"
            "2. Cite sources and distinguish facts from inferences.\n"
            "3. Identify gaps in available information.\n"
            "4. Structure findings with clear headings and bullet points.\n"
            "5. Provide actionable takeaways and next-step recommendations.\n\n"
            "Be thorough but concise. Prioritize primary sources. "
            "When uncertain, state your confidence level."
        )

    def _get_temperature(self, task: Task) -> float:
        return 0.3

    def _get_max_tokens(self, task: Task) -> int:
        return 8192


class WriterAgent(SubAgent):
    """Agent specialized in content creation and editing."""

    def __init__(self, llm: LLMManager):
        super().__init__(llm, name="WriterAgent")

    def get_profile(self) -> AgentProfile:
        return AgentProfile(
            agent_id=self.agent_id, name=self.name,
            capabilities=[AgentCapability.WRITING,
                          AgentCapability.SUMMARIZATION],
            supported_intents=["write", "draft", "compose", "create",
                               "edit", "rewrite", "blog", "email"],
            cost_per_1k_tokens=0.06, avg_latency_ms=3000, priority=2,
            preferred_capability="writing",
        )

    def get_system_prompt(self) -> str:
        return (
            "You are an expert content writer and editor. Your role is to:\n"
            "1. Produce clear, engaging, well-structured prose.\n"
            "2. Adapt tone and style to the target audience and format.\n"
            "3. Use active voice and concrete language.\n"
            "4. Ensure logical flow with smooth transitions.\n"
            "5. Proofread for grammar, clarity, and conciseness.\n\n"
            "When editing, preserve the author's voice while improving "
            "clarity and impact."
        )

    def _get_temperature(self, task: Task) -> float:
        creative = {"blog", "story", "creative", "poem"}
        if any(kw in task.input_text.lower() for kw in creative):
            return 0.9
        return 0.7

    def _get_max_tokens(self, task: Task) -> int:
        return 8192


class CodeAgent(SubAgent):
    """Agent specialized in code generation, debugging, and refactoring."""

    def __init__(self, llm: LLMManager):
        super().__init__(llm, name="CodeAgent")

    def get_profile(self) -> AgentProfile:
        return AgentProfile(
            agent_id=self.agent_id, name=self.name,
            capabilities=[AgentCapability.CODE_GENERATION,
                          AgentCapability.ANALYSIS],
            supported_intents=["code", "implement", "debug", "refactor",
                               "build", "program", "script", "function",
                               "test", "optimize"],
            cost_per_1k_tokens=0.06, avg_latency_ms=4000, priority=2,
            preferred_capability="code",
        )

    def get_system_prompt(self) -> str:
        return (
            "You are a senior software engineer. Your role is to:\n"
            "1. Write clean, production-quality code with proper error "
            "   handling, type hints, and documentation.\n"
            "2. Follow language-specific best practices and idioms.\n"
            "3. Include docstrings, inline comments for complex logic, "
            "   and usage examples.\n"
            "4. Consider edge cases, security, and performance.\n"
            "5. When debugging, explain root cause before the fix.\n\n"
            "Default to Python unless specified. Use modern features "
            "(Python 3.11+, ES2024, etc.)."
        )

    def _get_temperature(self, task: Task) -> float:
        return 0.2

    def _get_max_tokens(self, task: Task) -> int:
        return 16384


class AnalysisAgent(SubAgent):
    """Agent specialized in data analysis and strategic reasoning."""

    def __init__(self, llm: LLMManager):
        super().__init__(llm, name="AnalysisAgent")

    def get_profile(self) -> AgentProfile:
        return AgentProfile(
            agent_id=self.agent_id, name=self.name,
            capabilities=[AgentCapability.ANALYSIS,
                          AgentCapability.PLANNING],
            supported_intents=["analyze", "compare", "evaluate", "assess",
                               "reason", "plan", "review", "strategy",
                               "decide", "recommend"],
            cost_per_1k_tokens=0.06, avg_latency_ms=3500, priority=1,
            preferred_capability="analysis",
        )

    def get_system_prompt(self) -> str:
        return (
            "You are a strategic analyst and critical thinker. Your role:\n"
            "1. Break down complex problems into structured components.\n"
            "2. Evaluate options with clear criteria and trade-offs.\n"
            "3. Support conclusions with data and logical reasoning.\n"
            "4. Identify risks, assumptions, and blind spots.\n"
            "5. Present findings with executive summaries and actionable "
            "   recommendations.\n\n"
            "Use SWOT, cost-benefit, decision matrices where appropriate. "
            "Quantify impact whenever possible."
        )

    def _get_temperature(self, task: Task) -> float:
        return 0.4

    def _get_max_tokens(self, task: Task) -> int:
        return 8192


class SummarizerAgent(SubAgent):
    """Agent specialized in condensing and summarizing content."""

    def __init__(self, llm: LLMManager):
        super().__init__(llm, name="SummarizerAgent")

    def get_profile(self) -> AgentProfile:
        return AgentProfile(
            agent_id=self.agent_id, name=self.name,
            capabilities=[AgentCapability.SUMMARIZATION],
            supported_intents=["summarize", "tldr", "brief", "condense",
                               "recap", "overview", "digest"],
            cost_per_1k_tokens=0.001, avg_latency_ms=1500, priority=3,
            preferred_capability="summarization",
        )

    def get_system_prompt(self) -> str:
        return (
            "You are an expert summarizer. Your role is to:\n"
            "1. Distill content to essential points without losing nuance.\n"
            "2. Preserve the original author's intent and tone.\n"
            "3. Structure: one-line TL;DR, key points, action items.\n"
            "4. Adapt length to the request.\n\n"
            "Prioritize: accuracy > completeness > brevity."
        )

    def _get_temperature(self, task: Task) -> float:
        return 0.2

    def _get_max_tokens(self, task: Task) -> int:
        return 2048


class PlannerAgent(SubAgent):
    """Meta-agent that decomposes complex tasks into sub-task plans."""

    def __init__(self, llm: LLMManager):
        super().__init__(llm, name="PlannerAgent")

    def get_profile(self) -> AgentProfile:
        return AgentProfile(
            agent_id=self.agent_id, name=self.name,
            capabilities=[AgentCapability.PLANNING],
            supported_intents=["plan", "decompose", "break_down",
                               "strategize", "roadmap"],
            cost_per_1k_tokens=0.002, avg_latency_ms=2000, priority=0,
            preferred_capability="analysis",
        )

    def get_system_prompt(self) -> str:
        return (
            "You are a task decomposition specialist. Your role is to:\n"
            "1. Break a complex request into ordered, actionable sub-tasks.\n"
            "2. For each sub-task, specify:\n"
            "   - A clear one-line description\n"
            "   - The agent type (research, write, code, analyze)\n"
            "   - Dependencies on other sub-tasks\n"
            "   - Estimated complexity (low / medium / high)\n"
            "3. Return the plan as a JSON array.\n\n"
            "Keep plans minimal — fewest steps that cover full scope."
        )

    def _get_temperature(self, task: Task) -> float:
        return 0.2

    def _get_max_tokens(self, task: Task) -> int:
        return 2048
