# Po — The AI Operator That Proves Its Work

Po is an AI growth operator for B2B micro-SaaS / indie founders. Unlike "run
your whole company while you sleep" incumbents, Po wins on **trust, not
autonomy**: it validates before it spends, verifies that every action actually
worked, and gates risky/irreversible actions behind one-tap mobile approval.

See [`IMPLEMENTATION_PLAN.md`](./IMPLEMENTATION_PLAN.md) for the full product
thesis, roadmap, and rationale (derived from the research report).

---

## Repository layout

| Path | What it is | Role in the product |
|------|------------|---------------------|
| [`backend/`](./backend) | **Constraint-Optimized LLM Agent Orchestration System v2** — a runnable Python/FastAPI multi-provider orchestration framework (6 providers, 6 sub-agents, constraint engine, fallback chains, circuit breakers, streaming). | The **agent orchestration layer**. Po's planning/execution agents run on top of this. |
| [`web/`](./web) | **COO Engine site** — a static landing page plus an in-browser React dashboard that simulates constraint-optimized routing (fitness scoring, fallback, predictive spawn, cost-aware retirement). | The **front end + public demo**. Becomes the reliability dashboard and operator console. |
| [`IMPLEMENTATION_PLAN.md`](./IMPLEMENTATION_PLAN.md) | The phased build plan. | Product strategy and build order. |
| `Research Report.pdf` | The "Beating Polsia" competitive analysis. | Source of the product thesis. |

---

## How the pieces map to the product

The research report identifies three structural gaps in every incumbent —
**validation**, **verification**, and **trust/control**. The two codebases here
already supply the hard infrastructure those gaps require:

- **Constraint-first execution** (the report's budget governor + circuit
  breakers) is already implemented in `backend/` via the `ConstraintEngine`,
  hard token/cost budgets, and per-provider circuit breakers in `LLMManager`.
- **Cost-aware, provider-agnostic routing** (the report's "route by task, stay
  vendor-agnostic to avoid price shocks") is the `ModelSelector` +
  `FallbackChain` system.
- **The operator console + public reliability dashboard** the report calls for
  is prototyped by the `web/` COO Engine dashboard (decision audit trail, agent
  health, budget gauges) — currently in simulation mode, to be wired to the
  backend's `/v2/status` and `/v2/health` endpoints.

### What still needs building on top (per the plan)

The current `backend/` is a strong **execution + routing core** but does not yet
implement Po's three differentiators. The next layers to add:

1. **Validation gate** — a pre-execution node (demand / competitor density / ICP
   / willingness-to-pay scoring) that blocks spend on unvalidated ideas.
2. **Verification layer** — a post-action checker (URL returns 200, email lands,
   ad live within cap, Stripe webhook fired) that auto-refunds failed actions.
3. **Human-in-the-loop approval gates** — interrupt/resume on irreversible
   actions, surfaced to a mobile approvals queue.

These map directly onto the existing pipeline: the orchestrator's
`ExecutionPipeline.execute_task` is the natural insertion point for a
validation pre-hook and a verification post-hook, and the `ConstraintEngine`
already gives us the budget primitives.

---

## Quick start

### Backend (orchestration API)

```bash
cd backend
cp .env.example .env          # set at least ONE provider API key
pip install -r requirements.txt
uvicorn orchestrator_agent.server:app --reload --port 8000
```

Then `POST http://localhost:8000/v2/orchestrate` with `{"input": "..."}`.
See [`backend/README.md`](./backend/README.md) for full API docs and the Python SDK.

Run the tests:

```bash
cd backend && python -m pytest tests/ -q
```

### Web (landing + dashboard)

The site is static and the dashboard runs entirely in the browser in simulation
mode — no backend required to demo it.

```bash
cd web && python3 -m http.server 5173
# open http://localhost:5173/index.html
```

---

## Status

- ✅ Orchestration backend imported, parses clean.
- ✅ COO Engine site (landing + simulated dashboard) imported.
- ✅ **Validation gate, verification layer, and HITL approval gates** built and
  wired into `ExecutionPipeline` + the API.
  See [`backend/README.md`](./backend/README.md#po-trust-layer).
- ✅ **Real validation signals** behind a `SignalScorer` interface
  (`signals.py`): Google Suggest demand/competitor + Reddit WTP, with
  per-dimension heuristic fallback. `ValidationGate.with_live_signals()`.
- ✅ **Real side-effecting verifiers** (`verifiers.py`): deploy health (HTTP),
  email deliverability (SPF/DMARC/DKIM), Stripe webhook (HMAC signature).
- ✅ **Live web console** (`web/live.html`) wired to `/v2/status`, `/v2/health`,
  and `/v2/approvals`, driving the approval queue. CORS enabled on the API.
- ✅ **Trust-layer persistence** (`persistence.py`): `TrustStore` interface with
  an in-memory default and a Postgres backend (`DATABASE_URL`). Persists
  approvals / runs / validations, **rehydrates pending approvals on restart**
  (resumable), and powers `/v2/runs` + `/v2/stats`. SQL validated against a real
  PostgreSQL.
- ✅ Live console shows persisted reliability metrics (`/v2/stats`) and is the
  **default** dashboard CTA (browser simulation demoted to secondary).
- ✅ **Checkpointed multi-step workflows** (`checkpoint.py`): a `WorkflowRunner`
  saves a `WorkflowState` after every step and resumes from the last checkpoint
  after a crash, failure, or approval pause. Endpoints `/v2/workflows[/{id}]`.
- ✅ **Auto-generated workflow plans** from `PlannerAgent`: a single high-level
  goal is decomposed into ordered sub-tasks with intent mapping, then executed
  through the checkpointed workflow runner. Endpoint `POST /v2/workflows/plan`.
- ✅ **End-to-end integration tests** through the real `OrchestratorAgent` with
  a fake LLM provider: full orchestration, validation, plan→workflow, approval
  gates, persistence, batch, and status/health paths exercised.
- ✅ **Action tools layer** (`tools.py`): executable tools agents can invoke —
  email outbound (Resend API), content generation (LLM), web research, deploy
  health check, landing page generator + deployer. Each tool returns
  `verify_actions` specs for the verification layer. `ToolRegistry` + 5
  endpoints (`/v2/tools`, `/v2/tools/execute`).
- ✅ **Interactive CLI** (`python -m orchestrator_agent`): rich terminal
  experience with color-coded output, constraint budget bars, validation/
  verification/approval display, workflow planning, and live cost tracking.
- ✅ **Operator console** (`web/operator.html`): full-featured dashboard with
  sidebar navigation, KPI cards, constraint gauges, cost chart, provider health,
  approval queue, workflow timeline, run history table, and single-task
  orchestration — mobile-responsive.
- ✅ **Workflow scheduler** (`scheduler.py`): cron-like recurring workflows,
  one-shot delayed execution, pause/resume, morning digest reports with verified
  metrics. Endpoints: `/v2/schedules`, `/v2/scheduler/start|stop`, `/v2/digest`.
- **129/131 tests passing** (129 + 2 Postgres tests that run when
  `DATABASE_URL` is set).
