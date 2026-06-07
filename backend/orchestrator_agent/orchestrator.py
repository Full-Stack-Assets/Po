"""
OrchestratorAgent v2 — fully wired to multi-provider LLM backends.
"""

from __future__ import annotations
from typing import Any, AsyncIterator, Dict, List, Optional
import asyncio
import logging
import os

from orchestrator_agent.models import (
    Task, TaskContext, TaskStatus, AgentResult, AgentProfile,
    AgentCapability, Constraint, ExecutionMode,
)
from orchestrator_agent.llm_providers import (
    Message, LLMResponse, LLMChunk, ProviderConfig, ProviderType,
)
from orchestrator_agent.llm_manager import LLMManager, FallbackChain
from orchestrator_agent.agents import (
    SubAgent, ResearchAgent, WriterAgent, CodeAgent,
    AnalysisAgent, SummarizerAgent, PlannerAgent,
)
from orchestrator_agent.validation import ValidationGate, ValidationResult
from orchestrator_agent.verification import VerificationLayer
from orchestrator_agent.approvals import (
    ApprovalManager, ApprovalPolicy, ApprovalDecision, ApprovalType,
)

logger = logging.getLogger(__name__)


# ── Constraint Engine ─────────────────────────────────────────────────

class ConstraintEngine:
    def __init__(self):
        self._constraints: Dict[str, Constraint] = {}

    def add_constraint(self, constraint: Constraint) -> None:
        self._constraints[constraint.name] = constraint

    def consume(self, name: str, amount: float) -> bool:
        c = self._constraints.get(name)
        if c is None:
            return True
        return c.consume(amount)

    def check_feasibility(self, reqs: Dict[str, float]) -> bool:
        return all(
            self._constraints.get(n, Constraint(n, float("inf"))).remaining >= a
            for n, a in reqs.items()
        )

    def get_status(self) -> List[Dict]:
        return [
            {
                "name": c.name,
                "max": c.max_value,
                "used": round(c.current_value, 6),
                "remaining": round(c.remaining, 6),
                "utilization": f"{c.utilization:.1%}",
                "unit": c.unit,
                "exceeded": c.is_exceeded,
            }
            for c in self._constraints.values()
        ]

    def reset_all(self) -> None:
        for c in self._constraints.values():
            c.reset()


# ── Intent Classifier ─────────────────────────────────────────────────

class IntentClassifier:
    INTENT_KEYWORDS = {
        "research":   ["research", "find", "lookup", "search", "discover",
                       "investigate", "explore"],
        "write":      ["write", "draft", "compose", "create", "author",
                       "blog", "email", "letter", "essay"],
        "code":       ["code", "implement", "build", "debug", "program",
                       "script", "function", "refactor", "test", "deploy"],
        "analyze":    ["analyze", "compare", "evaluate", "assess", "reason",
                       "plan", "review", "strategy", "recommend", "decide"],
        "summarize":  ["summarize", "tldr", "brief", "condense", "recap",
                       "overview", "digest"],
        "plan":       ["plan", "decompose", "break down", "roadmap",
                       "strategize", "outline"],
    }

    def __init__(self, llm: Optional[LLMManager] = None):
        self.llm = llm

    def classify_fast(self, text: str) -> str:
        text_lower = text.lower()
        scores = {}
        for intent, keywords in self.INTENT_KEYWORDS.items():
            scores[intent] = sum(1 for kw in keywords if kw in text_lower)
        best = max(scores, key=scores.get)
        return best if scores[best] > 0 else "research"

    async def classify(self, text: str) -> str:
        fast = self.classify_fast(text)
        text_lower = text.lower()
        score = sum(
            1 for kw in self.INTENT_KEYWORDS.get(fast, [])
            if kw in text_lower
        )
        if score >= 2:
            return fast

        if self.llm:
            try:
                resp = await self.llm.complete(
                    messages=[
                        Message(
                            role="system",
                            content=(
                                "Classify the user's intent into exactly one "
                                "category. Respond with only the category name.\n"
                                "Categories: research, write, code, analyze, "
                                "summarize, plan"
                            ),
                        ),
                        Message(role="user", content=text),
                    ],
                    capability="classification",
                    temperature=0.0,
                    max_tokens=10,
                )
                if resp.success:
                    label = resp.content.strip().lower()
                    if label in self.INTENT_KEYWORDS:
                        return label
            except Exception:
                pass
        return fast


# ── Agent Registry ────────────────────────────────────────────────────

class AgentRegistry:
    def __init__(self):
        self._agents: Dict[str, SubAgent] = {}
        self._profiles: Dict[str, AgentProfile] = {}

    def register(self, agent: SubAgent) -> None:
        profile = agent.get_profile()
        self._agents[profile.agent_id] = agent
        self._profiles[profile.agent_id] = profile
        logger.info(f"Registered agent: {profile.name} ({profile.agent_id})")

    def get_agent(self, agent_id: str) -> Optional[SubAgent]:
        return self._agents.get(agent_id)

    def get_profile(self, agent_id: str) -> Optional[AgentProfile]:
        return self._profiles.get(agent_id)

    def list_agents(self) -> List[AgentProfile]:
        return [p for p in self._profiles.values() if p.enabled]

    def find_for_intent(self, intent: str) -> List[SubAgent]:
        return [
            self._agents[p.agent_id]
            for p in self._profiles.values()
            if intent in p.supported_intents and p.enabled
        ]


# ── Task Router ───────────────────────────────────────────────────────

class TaskRouter:
    def __init__(self, registry: AgentRegistry,
                 constraint_engine: ConstraintEngine):
        self.registry = registry
        self.constraint_engine = constraint_engine

    def route(self, task: Task) -> Optional[SubAgent]:
        candidates = self.registry.find_for_intent(task.intent)
        if not candidates:
            return None
        scored = [(a, self._score(a, task)) for a in candidates]
        scored.sort(key=lambda x: x[1], reverse=True)
        for agent, score in scored:
            profile = self.registry.get_profile(agent.agent_id)
            if profile and profile.active_tasks < profile.max_concurrent:
                return agent
        return scored[0][0] if scored else None

    def _score(self, agent: SubAgent, task: Task) -> float:
        profile = self.registry.get_profile(agent.agent_id)
        if not profile:
            return 0.0
        score = 10.0 if task.intent in profile.supported_intents else 0.0
        score -= profile.cost_per_1k_tokens * 2
        score -= profile.avg_latency_ms / 1000.0
        score += profile.priority * 2
        load = profile.active_tasks / max(profile.max_concurrent, 1)
        score -= load * 5
        return score


# ── Execution Pipeline ────────────────────────────────────────────────

class ExecutionPipeline:
    def __init__(self, router: TaskRouter,
                 constraint_engine: ConstraintEngine,
                 validation_gate: Optional["ValidationGate"] = None,
                 verification_layer: Optional["VerificationLayer"] = None,
                 approval_manager: Optional["ApprovalManager"] = None):
        self.router = router
        self.constraint_engine = constraint_engine
        # Po trust layer (all optional — pipeline works without them)
        self.validation_gate = validation_gate
        self.verification_layer = verification_layer
        self.approval_manager = approval_manager
        self._tasks: Dict[str, Task] = {}

    async def execute_task(self, task: Task,
                           context: TaskContext) -> AgentResult:
        self._tasks[task.task_id] = task
        task.status = TaskStatus.RUNNING

        # ── 1. Validation gate (pre-execution) ─────────────────────────
        gated = await self._run_validation(task)
        if gated is not None:
            return gated

        # ── 2. Approval gate (human-in-the-loop) ───────────────────────
        gated = self._run_approval_gate(task)
        if gated is not None:
            return gated

        agent = self.router.route(task)
        if agent is None:
            task.status = TaskStatus.FAILED
            return AgentResult(
                agent_id="none", task_id=task.task_id, output="",
                success=False,
                error=f"No agent for intent '{task.intent}'",
            )
        profile = self.router.registry.get_profile(agent.agent_id)
        if profile:
            profile.active_tasks += 1
        try:
            task.assigned_agent = agent.agent_id
            result = await agent.execute(task, context)
            self.constraint_engine.consume("token_budget", result.tokens_used)
            self.constraint_engine.consume("cost_budget", result.cost)
            # ── 3. Verification layer (post-execution) ─────────────────
            await self._run_verification(result, task)
            task.status = (
                TaskStatus.COMPLETED if result.success else TaskStatus.FAILED
            )
            task.result = result
            return result
        except Exception as e:
            logger.exception(f"Task {task.task_id} failed")
            task.status = TaskStatus.FAILED
            return AgentResult(
                agent_id=agent.agent_id, task_id=task.task_id,
                output="", success=False, error=str(e),
            )
        finally:
            if profile:
                profile.active_tasks = max(0, profile.active_tasks - 1)

    # ── Trust-layer hooks ──────────────────────────────────────────────

    async def _run_validation(self, task: Task) -> Optional[AgentResult]:
        """Returns a blocking AgentResult if validation fails, else None."""
        if not (self.validation_gate
                and task.metadata.get("require_validation")):
            return None
        vr = await self.validation_gate.validate(task.input_text)
        task.metadata["validation"] = vr
        if vr.is_blocking and not task.metadata.get("validation_override"):
            task.status = TaskStatus.FAILED
            return AgentResult(
                agent_id="validation_gate", task_id=task.task_id, output="",
                success=False,
                error=(f"Validation failed (score={vr.overall_score}/100, "
                       f"{vr.score.value}). {vr.rationale}"),
                metadata={"validation": vr.to_dict()},
            )
        return None

    def _run_approval_gate(self, task: Task) -> Optional[AgentResult]:
        """Returns an awaiting-approval AgentResult if gated, else None."""
        if not self.approval_manager or task.metadata.get("approved"):
            return None
        atype = self.approval_manager.policy.requires_approval(task)
        if atype is None or self.approval_manager.auto_approve:
            return None
        req = self.approval_manager.create(
            type=atype,
            summary=task.input_text[:160],
            payload={"task_id": task.task_id, "intent": task.intent,
                     "input": task.input_text},
        )
        task.metadata["approval_id"] = req.approval_id
        task.status = TaskStatus.AWAITING_APPROVAL
        return AgentResult(
            agent_id="approval_gate", task_id=task.task_id, output="",
            success=False, error="awaiting_approval",
            metadata={"approval_id": req.approval_id,
                      "approval_type": atype.value},
        )

    async def _run_verification(self, result: AgentResult,
                                task: Optional[Task] = None) -> None:
        if not self.verification_layer:
            return
        vresults = []
        if result.success:
            vresults += await self.verification_layer.verify_output(
                result.output)
        # Explicit, side-effecting action checks declared on the task.
        specs = task.metadata.get("verify_actions") if task else None
        if specs:
            vresults += await self.verification_layer.verify_actions(specs)
        if not vresults:
            return
        summary = self.verification_layer.summarize(vresults)
        result.metadata["verification"] = summary
        result.metadata["verification_details"] = [v.to_dict()
                                                    for v in vresults]
        if (not summary["all_passed"]
                and self.verification_layer.fail_on_unverified):
            # Auto-refund the budget consumed by an action that didn't verify.
            self.constraint_engine.consume("token_budget",
                                           -result.tokens_used)
            self.constraint_engine.consume("cost_budget", -result.cost)
            result.metadata["refunded"] = True
            result.success = False
            result.error = "verification_failed"

    async def resume_task(self, approval_id: str, context: TaskContext,
                          *, approved: bool = True,
                          edited_input: Optional[str] = None) -> AgentResult:
        """Resume a task that was paused awaiting approval."""
        if self.approval_manager is None:
            raise RuntimeError("No approval manager configured")
        req = self.approval_manager.get(approval_id)
        if req is None:
            return AgentResult(agent_id="approval_gate", task_id="",
                               output="", success=False,
                               error=f"Unknown approval '{approval_id}'")
        task = self._tasks.get(req.payload.get("task_id", ""))
        if task is None:
            return AgentResult(agent_id="approval_gate", task_id="",
                               output="", success=False,
                               error="Original task no longer available")
        decision = (ApprovalDecision.APPROVED if approved
                    else ApprovalDecision.REJECTED)
        edited_payload = ({"input": edited_input}
                          if edited_input is not None else None)
        self.approval_manager.decide(approval_id, decision, edited_payload)
        if not approved:
            task.status = TaskStatus.CANCELLED
            return AgentResult(agent_id="approval_gate",
                               task_id=task.task_id, output="",
                               success=False, error="approval_rejected")
        if edited_input is not None:
            task.input_text = edited_input
        task.metadata["approved"] = True
        return await self.execute_task(task, context)

    async def execute_batch(self, tasks: List[Task], context: TaskContext,
                            mode: ExecutionMode = ExecutionMode.SEQUENTIAL
                            ) -> List[AgentResult]:
        if mode == ExecutionMode.SEQUENTIAL:
            results = []
            for t in tasks:
                results.append(await self.execute_task(t, context))
            return results
        elif mode == ExecutionMode.CONCURRENT:
            return list(await asyncio.gather(
                *[self.execute_task(t, context) for t in tasks]
            ))
        elif mode == ExecutionMode.HIERARCHICAL:
            if not tasks:
                return []
            parent = await self.execute_task(tasks[0], context)
            rest = list(await asyncio.gather(
                *[self.execute_task(t, context) for t in tasks[1:]]
            ))
            return [parent, *rest]
        return []


# ── Default Configs ───────────────────────────────────────────────────

def build_default_configs() -> List[ProviderConfig]:
    configs = []
    if os.environ.get("OPENAI_API_KEY"):
        configs.append(ProviderConfig(
            provider_type=ProviderType.OPENAI,
            api_key=os.environ["OPENAI_API_KEY"],
            default_model="gpt-4.1-mini",
        ))
    if os.environ.get("ANTHROPIC_API_KEY"):
        configs.append(ProviderConfig(
            provider_type=ProviderType.ANTHROPIC,
            api_key=os.environ["ANTHROPIC_API_KEY"],
            default_model="claude-sonnet-4-5",
        ))
    if (os.environ.get("AZURE_OPENAI_API_KEY")
            and os.environ.get("AZURE_OPENAI_ENDPOINT")):
        configs.append(ProviderConfig(
            provider_type=ProviderType.AZURE_OPENAI,
            api_key=os.environ["AZURE_OPENAI_API_KEY"],
            base_url=os.environ["AZURE_OPENAI_ENDPOINT"],
            api_version=os.environ.get("AZURE_OPENAI_API_VERSION",
                                       "2025-03-01-preview"),
            deployment_name=os.environ.get("AZURE_OPENAI_DEPLOYMENT",
                                           "gpt-4.1"),
            default_model=os.environ.get("AZURE_OPENAI_DEPLOYMENT",
                                         "gpt-4.1"),
        ))
    if os.environ.get("GOOGLE_API_KEY"):
        configs.append(ProviderConfig(
            provider_type=ProviderType.GEMINI,
            api_key=os.environ["GOOGLE_API_KEY"],
            default_model="gemini-2.5-flash",
        ))
    if os.environ.get("MISTRAL_API_KEY"):
        configs.append(ProviderConfig(
            provider_type=ProviderType.MISTRAL,
            api_key=os.environ["MISTRAL_API_KEY"],
            default_model="mistral-small-latest",
        ))
    ollama_url = os.environ.get("OLLAMA_BASE_URL", "")
    if ollama_url:
        configs.append(ProviderConfig(
            provider_type=ProviderType.OLLAMA,
            base_url=ollama_url,
            default_model="llama3",
        ))
    return configs


def build_default_fallbacks() -> List[FallbackChain]:
    return [
        FallbackChain("research").add(
            ProviderType.OPENAI, "gpt-4.1"
        ).add(ProviderType.ANTHROPIC, "claude-sonnet-4-5"
        ).add(ProviderType.GEMINI, "gemini-2.5-pro"
        ).add(ProviderType.MISTRAL, "mistral-large-latest"
        ).add(ProviderType.OLLAMA, "llama3"),

        FallbackChain("code").add(
            ProviderType.ANTHROPIC, "claude-sonnet-4-5"
        ).add(ProviderType.OPENAI, "o4-mini"
        ).add(ProviderType.GEMINI, "gemini-2.5-pro"
        ).add(ProviderType.MISTRAL, "codestral-latest"
        ).add(ProviderType.OLLAMA, "codellama"),

        FallbackChain("writing").add(
            ProviderType.ANTHROPIC, "claude-sonnet-4-5"
        ).add(ProviderType.OPENAI, "gpt-4.1"
        ).add(ProviderType.GEMINI, "gemini-2.5-pro"
        ).add(ProviderType.MISTRAL, "mistral-large-latest"
        ).add(ProviderType.OLLAMA, "llama3"),

        FallbackChain("fast").add(
            ProviderType.OPENAI, "gpt-4.1-nano"
        ).add(ProviderType.GEMINI, "gemini-2.0-flash"
        ).add(ProviderType.MISTRAL, "mistral-small-latest"
        ).add(ProviderType.ANTHROPIC, "claude-haiku-3.5"),
    ]


# ── OrchestratorAgent v2 ─────────────────────────────────────────────

class OrchestratorAgent:
    """
    Central orchestrator with full multi-provider LLM integration.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.llm = LLMManager()
        self.constraint_engine = ConstraintEngine()
        self.registry = AgentRegistry()
        self._contexts: Dict[str, TaskContext] = {}
        self._initialized = False

    async def initialize(
        self, provider_configs: Optional[List[ProviderConfig]] = None,
    ) -> None:
        configs = provider_configs or build_default_configs()
        if not configs:
            raise RuntimeError(
                "No LLM providers configured. Set at least one API key "
                "env var (OPENAI_API_KEY, ANTHROPIC_API_KEY, etc.)."
            )
        for cfg in configs:
            self.llm.add_provider(cfg)
        for chain in build_default_fallbacks():
            self.llm.add_fallback_chain(chain)
        await self.llm.initialize()

        defaults = self.config.get("constraints", {})
        self.constraint_engine.add_constraint(Constraint(
            name="token_budget",
            max_value=defaults.get("max_tokens", 100_000),
            unit="tokens", hard_limit=True,
        ))
        self.constraint_engine.add_constraint(Constraint(
            name="cost_budget",
            max_value=defaults.get("max_cost", 5.00),
            unit="USD", hard_limit=True,
        ))
        self.constraint_engine.add_constraint(Constraint(
            name="latency_budget",
            max_value=defaults.get("max_latency_ms", 30_000),
            unit="ms", hard_limit=False,
        ))

        for agent_cls in [ResearchAgent, WriterAgent, CodeAgent,
                          AnalysisAgent, SummarizerAgent, PlannerAgent]:
            self.registry.register(agent_cls(self.llm))

        # ── Po trust layer ─────────────────────────────────────────────
        trust = self.config.get("trust_layer", {})
        self.validation_gate = (
            ValidationGate(self.llm) if trust.get("validation", True) else None
        )
        self.verification_layer = VerificationLayer(
            enabled=trust.get("verification", True),
            fail_on_unverified=trust.get("fail_on_unverified", False),
        )
        self.approval_manager = (
            ApprovalManager(auto_approve=trust.get("auto_approve", True))
            if trust.get("approvals", True) else None
        )

        self.router = TaskRouter(self.registry, self.constraint_engine)
        self.pipeline = ExecutionPipeline(
            self.router, self.constraint_engine,
            validation_gate=self.validation_gate,
            verification_layer=self.verification_layer,
            approval_manager=self.approval_manager,
        )
        self._initialized = True
        logger.info("OrchestratorAgent v2 ready (trust layer enabled)")

    async def shutdown(self) -> None:
        await self.llm.shutdown()

    def _get_context(self, conversation_id: str = "") -> TaskContext:
        if not conversation_id:
            ctx = TaskContext()
            self._contexts[ctx.conversation_id] = ctx
            return ctx
        if conversation_id not in self._contexts:
            self._contexts[conversation_id] = TaskContext(
                conversation_id=conversation_id
            )
        return self._contexts[conversation_id]

    async def orchestrate(
        self, user_input: str, conversation_id: str = "",
        mode: ExecutionMode = ExecutionMode.SEQUENTIAL,
        metadata: Optional[Dict] = None,
        validate: bool = False,
        validation_override: bool = False,
    ) -> Dict[str, Any]:
        if not self._initialized:
            raise RuntimeError("Call initialize() first")
        context = self._get_context(conversation_id)
        context.add_message("user", user_input)
        if metadata:
            context.metadata.update(metadata)

        classifier = IntentClassifier(self.llm)
        intent = await classifier.classify(user_input)
        task = Task(input_text=user_input, intent=intent)
        if validate:
            task.metadata["require_validation"] = True
        if validation_override:
            task.metadata["validation_override"] = True
        result = await self.pipeline.execute_task(task, context)

        return self._result_payload(context, task, result)

    def _result_payload(self, context: TaskContext, task: Task,
                        result: AgentResult) -> Dict[str, Any]:
        validation = task.metadata.get("validation")
        return {
            "conversation_id": context.conversation_id,
            "task_id": task.task_id,
            "intent": task.intent,
            "assigned_agent": task.assigned_agent,
            "status": task.status.value,
            "output": result.output,
            "success": result.success,
            "error": result.error,
            "tokens_used": result.tokens_used,
            "cost_usd": round(result.cost, 6),
            "latency_ms": round(result.latency_ms, 1),
            "model_used": result.model_used,
            "provider_used": result.provider_used,
            # ── Po trust layer ──────────────────────────────────────────
            "validation": (validation.to_dict()
                           if isinstance(validation, ValidationResult)
                           else None),
            "verification": result.metadata.get("verification"),
            "refunded": result.metadata.get("refunded", False),
            "approval": (
                {"id": result.metadata.get("approval_id"),
                 "type": result.metadata.get("approval_type")}
                if task.status == TaskStatus.AWAITING_APPROVAL else None
            ),
            "constraints": self.constraint_engine.get_status(),
            "provider_health": self.llm.get_health(),
        }

    async def decide_approval(
        self, approval_id: str, approved: bool = True,
        edited_input: Optional[str] = None, conversation_id: str = "",
    ) -> Dict[str, Any]:
        """Approve / reject / edit a pending approval and resume the task."""
        if not self._initialized:
            raise RuntimeError("Call initialize() first")
        context = self._get_context(conversation_id)
        result = await self.pipeline.resume_task(
            approval_id, context, approved=approved, edited_input=edited_input,
        )
        task = self.pipeline._tasks.get(result.task_id)
        if task is None:
            return {"success": result.success, "error": result.error}
        return self._result_payload(context, task, result)

    async def orchestrate_batch(
        self, inputs: List[str], conversation_id: str = "",
        mode: ExecutionMode = ExecutionMode.CONCURRENT,
    ) -> List[Dict[str, Any]]:
        context = self._get_context(conversation_id)
        classifier = IntentClassifier(self.llm)
        tasks = []
        for text in inputs:
            intent = await classifier.classify(text)
            tasks.append(Task(input_text=text, intent=intent))
        results = await self.pipeline.execute_batch(tasks, context, mode)
        return [
            {
                "task_id": t.task_id, "intent": t.intent,
                "status": t.status.value, "output": r.output,
                "success": r.success, "model": r.model_used,
                "provider": r.provider_used,
                "cost_usd": round(r.cost, 6),
            }
            for t, r in zip(tasks, results)
        ]

    async def stream_orchestrate(
        self, user_input: str, conversation_id: str = "",
    ) -> AsyncIterator[str]:
        if not self._initialized:
            raise RuntimeError("Call initialize() first")
        context = self._get_context(conversation_id)
        context.add_message("user", user_input)
        classifier = IntentClassifier(self.llm)
        intent = await classifier.classify(user_input)
        agents = self.registry.find_for_intent(intent)
        if not agents:
            yield "[Error: No agent available]"
            return
        agent = agents[0]
        profile = agent.get_profile()
        messages = context.to_messages(agent.get_system_prompt())
        messages.append(Message(role="user", content=user_input))
        async for chunk in self.llm.stream_complete(
            messages=messages, capability=profile.preferred_capability,
        ):
            yield chunk.content

    def get_status(self) -> Dict[str, Any]:
        return {
            "initialized": self._initialized,
            "agents": [
                {
                    "id": p.agent_id, "name": p.name,
                    "capabilities": [c.value for c in p.capabilities],
                    "intents": p.supported_intents,
                    "active": p.active_tasks,
                }
                for p in self.registry.list_agents()
            ],
            "constraints": self.constraint_engine.get_status(),
            "providers": self.llm.get_health(),
            "usage": self.llm.get_usage(),
            "models": self.llm.get_available_models(),
        }
