# Implementation Plan: "Po" — The AI Operator That Proves Its Work

> Derived from the Research Report ("Beating Polsia"). The repo now contains two
> imported foundations — `backend/` (the orchestration core) and `web/` (the
> landing page + dashboard); see [`README.md`](./README.md). The build below adds
> Po's three differentiators (validation, verification, HITL approval) on top.

## 1. Product Thesis

A cloud-hosted, mobile-first AI operator for **B2B micro-SaaS / indie founders**. It runs growth workflows (validated outbound, content, SEO/GEO, ad ops) with the three layers competitors lack:

1. **Validation gate** — never spend on an unvalidated idea (demand/competitor/ICP/WTP scoring → red/yellow/green).
2. **Verification layer** — every action independently proven to have worked (URL returns 200, email landed, ad live within cap, Stripe webhook fired). Failed actions auto-refund and are surfaced honestly.
3. **Human-in-the-loop approval gates** — one-tap mobile approve/edit/reject on irreversible/high-blast-radius actions; auto-approve safe/reversible ones.

Plus: public reliability dashboard, full code/data portability, transparent flat pricing ($49–99/mo, no rev share), budget governor + circuit breakers, vertical depth + data moat.

**Positioning:** "Polsia runs your company on a guess and hopes. We validate first, prove every action worked, and you approve anything risky from your phone. You own your code. No 20% tax."

## 2. Tech Stack

- **Frontend/API:** Next.js 14 (App Router) + TypeScript, Tailwind + shadcn/ui, PWA (mobile-first)
- **Orchestration:** LangGraph.js (`interrupt()` + `Command`, Postgres checkpointer for pause/resume over hours)
- **Models (routed):** Claude Opus for planning/reasoning; Sonnet for content; Haiku for classification/verification
- **Data:** Supabase (Postgres + Auth + Realtime + Storage), Drizzle ORM, pgvector for memory
- **Billing:** Stripe
- **Tools:** Resend (email), Vercel/Render (deploy), Browserbase (cloud browser), Google/Meta Ads (budget-capped), GitHub
- **Monorepo:** pnpm workspaces + Turborepo

## 3. Repo Structure (target)

```
apps/web/                 Next.js app (dashboard, public reliability page, API routes)
packages/agents/          LangGraph graph, nodes, tools, verification, validation, budget, memory
packages/db/              Drizzle schema + migrations
packages/shared/          Shared types/constants
workers/                  Nightly scheduler, verification worker, report generator
supabase/                 Config + seed
```

## 4. Core Agent Graph

```
START → validation_gate ──red──► require_override ──rejected──► END
          │ green/yellow
          ▼
        planning → budget_check ──over──► pause_and_notify → END
          │ within budget
          ▼
        approval_gate ──rejected──► END
          │ approved/auto
          ▼
        execution → verification ──pass──► next_step? ──yes──► budget_check
                         │ fail                    │ no
                         ▼                          ▼
                  retry_or_refund               reporting → END
                         │ (retries exhausted)
                         ▼
                  escalate_to_human → approval_gate
```

Verification is primarily **deterministic** (HTTP/API checks), not LLM-based, to avoid "who verifies the verifier."

## 5. Database Tables (Postgres/Drizzle)

users · companies · subscriptions · budgets · validations · workflows · workflow_runs · actions (audit trail) · verifications · approvals (HITL queue, with TTL) · reliability_stats · memory_embeddings (pgvector).

## 6. Build Order

### Phase 0 — Foundation (Days 1–3)
- Monorepo scaffold (pnpm + Turbo)
- Supabase + Drizzle schema + initial migration + pgvector
- Auth + dashboard shell + PWA manifest
- Stripe products/webhooks/checkout

### Phase 1 — MVP Core Loop (Days 4–14)
- Shared types/constants
- LangGraph skeleton + Postgres checkpointer + model router
- Validation gate (demand, competitor density, ICP, WTP scorers)
- Tool #1: Email outbound + deliverability verification
- Tool #2: Landing-page deploy + HTTP verification + content generation
- Approval gate (`interrupt()` → DB → push → resume via `Command`) + mobile approvals UI
- Budget governor + circuit breaker
- Verification layer wired after every execution (retry → refund on fail)
- Workflow runs list + run detail/audit-trail UI
- `/api/workflows` POST wiring the full loop end-to-end

### Phase 2 — Reliability & Retention (Days 15–25)
- Nightly cycle scheduler + morning verified report
- **Public reliability dashboard** (the marketing moat)
- Code/data export (one-click ZIP)
- More tools: SEO, ads (hard budget caps), cloud browser
- Spend anomaly detection

### Phase 3 — Depth & Moat (Days 26–40+)
- pgvector long-term memory
- Vertical playbooks (PH launch, cold outbound, SEO cluster, comparison page)
- Opt-in anonymized cross-account learning
- GEO/SEO content engine

### Phase 4 — Later
- Adjacent verticals, optional outcome-based pricing once public success rate is proven

## 7. Key Risk Mitigations
- **LLM cost:** model routing + per-action cost tracking + budget governor + pre-action cost estimate shown at approval
- **Verifier reliability:** deterministic checks first; structured-output LLM only where judgment is unavoidable
- **Stale approvals:** TTL auto-reject; graceful pause instead of indefinite block
- **Privacy:** PII filtering before logging; anonymization before cross-account learning; Supabase RLS for tenant isolation

## 8. Most Critical Files
- `packages/agents/src/graph/operator-graph.ts` — central state machine
- `packages/agents/src/graph/nodes/verification.ts` — the core wedge
- `packages/agents/src/graph/nodes/approval-gate.ts` — HITL interrupt/resume
- `packages/db/src/schema/index.ts` — data model underpinning audit/budget/dashboard/export
- `apps/web/app/api/workflows/route.ts` — frontend → agent entry point
