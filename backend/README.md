# Constraint-Optimized LLM Agent Orchestration System

**v2.0.0** — Multi-provider agent orchestration framework with intelligent routing, constraint management, and streaming support.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                      OrchestratorAgent v2                    │
│  ┌────────────┐  ┌────────────┐  ┌─────────────────────┐    │
│  │  Intent     │  │   Task     │  │   Constraint        │    │
│  │ Classifier  │→ │   Router   │→ │   Engine            │    │
│  │ (LLM-backed)│  │            │  │                     │    │
│  └────────────┘  └────────────┘  └─────────────────────┘    │
├──────────────────────────────────────────────────────────────┤
│            Sub-Agents (all wired to LLMManager)              │
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌────────┐ ┌───────┐ ┌───────┐ │
│  │Resrch│ │Writer│ │ Code │ │Analysis│ │Summrzr│ │Planner│ │
│  └──────┘ └──────┘ └──────┘ └────────┘ └───────┘ └───────┘ │
├──────────────────────────────────────────────────────────────┤
│                       LLMManager                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │ ModelSelector │  │  Fallback    │  │  Provider Health │   │
│  │ (per-task)    │  │  Chains      │  │  + Circuit Brkr  │   │
│  └──────────────┘  └──────────────┘  └──────────────────┘   │
├──────────────────────────────────────────────────────────────┤
│                    Provider Layer                             │
│  ┌───────┐ ┌─────────┐ ┌───────┐ ┌──────┐ ┌───────┐ ┌─────┐│
│  │OpenAI │ │Anthropic│ │Azure  │ │Gemini│ │Mistral│ │Ollam││
│  │GPT-4.1│ │Claude 4 │ │OpenAI │ │ 2.5  │ │Large  │ │Local││
│  └───────┘ └─────────┘ └───────┘ └──────┘ └───────┘ └─────┘│
└──────────────────────────────────────────────────────────────┘
```

## Supported Providers

| Provider      | Models                                    | API Key Env Var           |
|---------------|-------------------------------------------|---------------------------|
| OpenAI        | GPT-4.1, GPT-4.1 Mini/Nano, o4-mini      | `OPENAI_API_KEY`          |
| Anthropic     | Claude Sonnet 4.5, Opus 4, Haiku 3.5     | `ANTHROPIC_API_KEY`       |
| Azure OpenAI  | Any deployed model                        | `AZURE_OPENAI_API_KEY`    |
| Google Gemini | 2.5 Pro, 2.5 Flash, 2.0 Flash            | `GOOGLE_API_KEY`          |
| Mistral       | Large, Small, Codestral                   | `MISTRAL_API_KEY`         |
| Ollama        | LLaMA 3, CodeLLaMA, Mixtral, DeepSeek R1 | `OLLAMA_BASE_URL`         |

## Quick Start

### 1. Install

```bash
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env — set at least ONE provider API key
```

### 3. Run the API Server

```bash
uvicorn orchestrator_agent.server:app --reload --port 8000
```

### 4. Or use the Interactive CLI

```bash
python -m orchestrator_agent
```

### 5. Or use Docker

```bash
docker-compose up -d
```

## API Endpoints

| Method | Endpoint          | Description                        |
|--------|-------------------|------------------------------------|
| POST   | `/v2/orchestrate` | Single task orchestration          |
| POST   | `/v2/batch`       | Batch multi-task orchestration     |
| GET    | `/v2/status`      | System status (agents, constraints)|
| GET    | `/v2/models`      | List all available models          |
| GET    | `/v2/health`      | Provider health & usage metrics    |

### Example: Single Request

```bash
curl -X POST http://localhost:8000/v2/orchestrate \
  -H "Content-Type: application/json" \
  -d '{"input": "Research the latest trends in AI agents"}'
```

### Example: Streaming

```bash
curl -X POST http://localhost:8000/v2/orchestrate \
  -H "Content-Type: application/json" \
  -d '{"input": "Write a blog post about LLM orchestration", "stream": true}'
```

### Example: Batch

```bash
curl -X POST http://localhost:8000/v2/batch \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": [
      "Research competitor landscape",
      "Draft executive summary",
      "Analyze market sizing"
    ],
    "mode": "concurrent"
  }'
```

## Po Trust Layer

On top of the orchestration core, three optional gates implement Po's
"prove the work" differentiators (see the repo-root `README.md`). All are
enabled by default and configured via `config["trust_layer"]`.

| Gate | Module | What it does |
|------|--------|--------------|
| **Validation gate** | `validation.py` + `signals.py` | Scores an idea (demand / competitor / ICP / WTP) → red/yellow/green. A RED rating is **blocking** unless overridden. Pluggable scorers behind a `SignalScorer` interface: LLM-backed, a deterministic heuristic, or **live signals** (Google Suggest demand/competitor, Reddit WTP) via `trust_layer.live_signals: true` or `ValidationGate.with_live_signals(...)` — each degrades to heuristic per-dimension when offline. |
| **Approval gate** | `approvals.py` | Pauses risky intents (`write`→outreach, `code`→deploy) for one-tap human approve / edit / reject. Auto-approves safe, reversible work. Pending requests carry a TTL and auto-expire. |
| **Verification layer** | `verification.py` + `verifiers.py` | After execution, independently verifies the work. URL reachability is checked from the output; explicit `verify_actions` specs route to real verifiers — **deploy health** (HTTP status + body), **email deliverability** (SPF/DMARC/DKIM DNS), **Stripe webhook** (HMAC signature). With `fail_on_unverified`, a failed check flips the result and **auto-refunds** the action's budget. |

### Trust-layer endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v2/orchestrate` (`"validate": true`) | Run the validation gate before executing |
| GET  | `/v2/approvals` | List pending approval requests |
| POST | `/v2/approvals/{id}` | Approve / reject / edit and resume the task |

```python
# Validate before spending; override only if you really mean to.
result = await orch.orchestrate("Build a CRM for dog walkers", validate=True)
if result["validation"]["score"] == "red":
    ...  # blocked — pass validation_override=True to force

# Enable live network signals (Google Suggest, Reddit WTP) for validation.
orch = OrchestratorAgent(config={"trust_layer": {"live_signals": True}})
await orch.initialize()

# Human-in-the-loop: risky tasks pause with auto_approve disabled.
orch = OrchestratorAgent(config={"trust_layer": {"auto_approve": False}})
await orch.initialize()
res = await orch.orchestrate("Send cold outreach to 50 leads")  # -> awaiting_approval
await orch.decide_approval(res["approval"]["id"], approved=True)
```

```python
# Live demand signals behind the scorer interface (key-free public sources).
from orchestrator_agent import ValidationGate
gate = ValidationGate.with_live_signals()
result = await gate.validate("AI cold-outreach tool for B2B SaaS founders")
print(result.score.value, result.details["sources"])

# Real side-effecting verifiers for genuine actions.
from orchestrator_agent import VerificationLayer
layer = VerificationLayer(fail_on_unverified=True).register_defaults()
checks = await layer.verify_actions([
    {"type": "deploy_health", "url": "https://my-landing.vercel.app",
     "expect_substring": "Get started"},
    {"type": "email_deliverability", "domain": "mycompany.com"},
    {"type": "stripe_webhook", "payload": raw_body,
     "signature": stripe_sig_header, "secret": webhook_secret},
])
```

### Persistence (`persistence.py`)

Approvals, runs, and validations are written through a `TrustStore`. With no
database configured the default `InMemoryTrustStore` is used; set `DATABASE_URL`
(and have `asyncpg` installed) to use `PostgresTrustStore`, which creates its
schema on startup, **survives restarts** (pending approvals are rehydrated into
the queue and can still be resumed), and powers the reliability metrics.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v2/runs?limit=N` | Recent orchestration runs (audit trail) |
| GET | `/v2/stats` | Aggregate reliability metrics (success / verified-pass / refund rates) |

```python
orch = OrchestratorAgent(config={
    "persistence": {"dsn": "postgresql://user:pass@localhost:5432/po"},
})
await orch.initialize()        # creates schema, hydrates pending approvals
...
await orch.get_reliability_stats()
```

### Checkpointed workflows (`checkpoint.py`)

Multi-step plans run through a `WorkflowRunner` that saves a `WorkflowState`
checkpoint after **every** step (keyed by `thread_id` in the `TrustStore`). If a
step fails, the process restarts, or a step pauses for approval, the run resumes
from the last checkpoint instead of starting over — the synchronous analogue of
LangGraph's `interrupt()` + persistent checkpointer.

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v2/workflows/plan` | Auto-generate and run a workflow from a goal |
| POST | `/v2/workflows` | Start a workflow `{steps: [...], thread_id?}` |
| POST | `/v2/workflows/{thread_id}/resume` | Resume after a crash, failure, or approval |
| GET | `/v2/workflows/{thread_id}` | Current workflow state |

```python
# Steps are strings or {"input", "intent"}; risky intents pause for approval.
state = await orch.run_workflow([
    {"input": "research the ICP", "intent": "research"},
    {"input": "draft cold outreach", "intent": "write"},   # -> awaiting_approval
])
if state["status"] == "awaiting_approval":
    await orch.decide_approval(state["pending_approval_id"], approved=True)
    state = await orch.resume_workflow(state["thread_id"])  # continues to the end

# Or let the PlannerAgent decompose a high-level goal automatically.
state = await orch.plan_and_run_workflow("Grow my B2B SaaS to 100 users")
# The planner generates ordered sub-tasks with intent mapping, then the
# checkpointed runner executes them — pausing for approval on risky steps.
```

### Live web console

`web/live.html` is a zero-build operator console that connects to this API
(`/v2/status`, `/v2/health`, `/v2/approvals`, `/v2/stats`), shows the persisted
reliability metrics, and drives the approval queue from the browser. CORS is
enabled on the server for local development.

## Python SDK Usage

```python
import asyncio
from orchestrator_agent import OrchestratorAgent

async def main():
    orch = OrchestratorAgent(config={
        "constraints": {
            "max_tokens": 100_000,
            "max_cost": 5.00,
        }
    })
    await orch.initialize()

    # Single request
    result = await orch.orchestrate(
        "Analyze the competitive landscape for AI orchestration tools"
    )
    print(result["output"])
    print(f"Cost: ${result['cost_usd']}")
    print(f"Provider: {result['provider_used']}/{result['model_used']}")

    # Batch request (concurrent)
    results = await orch.orchestrate_batch([
        "Research market size",
        "Draft investor memo",
        "Build financial model assumptions",
    ])

    # Streaming
    async for token in orch.stream_orchestrate("Write a technical spec"):
        print(token, end="", flush=True)

    await orch.shutdown()

asyncio.run(main())
```

## Adding a Custom Agent

```python
from orchestrator_agent import SubAgent, AgentProfile, AgentCapability

class CustomAgent(SubAgent):
    def __init__(self, llm):
        super().__init__(llm, name="CustomAgent")

    def get_profile(self) -> AgentProfile:
        return AgentProfile(
            agent_id=self.agent_id,
            name=self.name,
            capabilities=[AgentCapability.TOOL_USE],
            supported_intents=["custom_intent"],
            preferred_capability="research",
        )

    def get_system_prompt(self) -> str:
        return "You are a custom agent specialized in..."
```

## Project Structure

```
orchestrator_agent/
├── __init__.py          # Package exports
├── __main__.py          # CLI entry point
├── models.py            # Core data models
├── llm_providers.py     # 6 LLM provider implementations
├── llm_manager.py       # Multi-provider coordinator
├── agents.py            # 6 wired sub-agents
├── orchestrator.py      # Main orchestrator + pipeline
└── server.py            # FastAPI REST API
```

## Key Features

- **Constraint-first execution** — token budgets, cost caps, latency limits
- **Automatic fallback** — if a provider fails, the next one is tried
- **Circuit breakers** — unhealthy providers are temporarily disabled
- **Model selection** — best model chosen per task capability
- **Cost tracking** — real-time USD cost tracking across all providers
- **Streaming** — end-to-end SSE streaming from API to providers

## License

Proprietary — Nicholas Albertson. All rights reserved.
