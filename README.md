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
  wired into `ExecutionPipeline` + the API. **40/40 unit tests passing.**
  See [`backend/README.md`](./backend/README.md#po-trust-layer).
- ⬜ Real validation signals (keyword/competitor/WTP scraping) behind the gate's
  scorer interface (currently LLM-backed + heuristic).
- ⬜ Real side-effecting verifiers (email deliverability, deploy health, Stripe
  webhook) alongside the HTTP checker.
- ⬜ Wire the web dashboard to live backend `/v2/status`, `/v2/health`, and
  `/v2/approvals`.
