#!/usr/bin/env python3
"""
End-to-end smoke test against a real LLM provider.

Usage:
    ANTHROPIC_API_KEY=sk-... python scripts/smoke_test.py
    # or with any other supported provider:
    OPENAI_API_KEY=sk-... python scripts/smoke_test.py

Runs five checks through the real OrchestratorAgent:
  1. Single orchestration (intent classification + agent execution)
  2. Validation gate (demand scoring via LLM)
  3. Plan → workflow (PlannerAgent decomposes goal, runner executes steps)
  4. Approval gate (pause + resume on a risky intent)
  5. Persistence (run recorded, stats aggregated)
"""

import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from orchestrator_agent.orchestrator import OrchestratorAgent

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
WARN = "\033[93m!\033[0m"


def section(name: str):
    print(f"\n{'─' * 60}")
    print(f"  {name}")
    print(f"{'─' * 60}")


async def main():
    t0 = time.time()
    errors = []

    # ── Init ──────────────────────────────────────────────────────────
    section("Initializing OrchestratorAgent with real provider(s)")
    orch = OrchestratorAgent(config={
        "trust_layer": {"auto_approve": True},
        "constraints": {"max_tokens": 100_000, "max_cost": 2.00},
    })
    try:
        await orch.initialize()
    except RuntimeError as e:
        print(f"{FAIL} {e}")
        print("\n  Set at least one provider API key in the environment.")
        sys.exit(1)
    providers = [p.value for p in orch.llm._providers]
    print(f"{PASS} Providers: {providers}")

    # ── 1. Single orchestration ───────────────────────────────────────
    section("1. Single orchestration")
    try:
        r = await orch.orchestrate(
            "What are the top 3 trends in AI agents in 2025? Answer in under 100 words.")
        assert r["success"], f"Failed: {r.get('error')}"
        print(f"{PASS} Intent: {r['intent']}")
        print(f"{PASS} Model:  {r['model_used']} via {r['provider_used']}")
        print(f"{PASS} Cost:   ${r['cost_usd']}")
        print(f"{PASS} Output: {r['output'][:200]}...")
    except Exception as e:
        print(f"{FAIL} {e}")
        errors.append(("single orchestration", str(e)))

    # ── 2. Validation gate ────────────────────────────────────────────
    section("2. Validation gate (LLM-backed scoring)")
    try:
        r = await orch.orchestrate(
            "A paid B2B SaaS tool for indie founders that automates "
            "validated cold outbound with per-month pricing",
            validate=True,
        )
        v = r.get("validation")
        assert v is not None, "No validation result returned"
        print(f"{PASS} Score:   {v['overall_score']}/100 → {v['score']}")
        print(f"{PASS} Demand:  {v['demand_score']}  Competitor: {v['competitor_score']}  "
              f"ICP: {v['icp_score']}  WTP: {v['wtp_score']}")
        print(f"{PASS} Backend: {v['backend']}")
        print(f"{PASS} Success: {r['success']}")
    except Exception as e:
        print(f"{FAIL} {e}")
        errors.append(("validation gate", str(e)))

    # ── 3. Plan → workflow ────────────────────────────────────────────
    section("3. Plan → Workflow (PlannerAgent + checkpointed runner)")
    try:
        w = await orch.plan_and_run_workflow(
            "Research the top 3 competitors to Zapier and summarize findings")
        assert w.get("status") == "completed", f"Status: {w.get('status')}, error: {w.get('error')}"
        results = w.get("results", [])
        print(f"{PASS} Status:  {w['status']}")
        print(f"{PASS} Steps:   {len(results)}")
        if w.get("plan_raw"):
            print(f"{PASS} Plan (first 200): {w['plan_raw'][:200]}...")
        for i, s in enumerate(results):
            status_icon = PASS if s["success"] else FAIL
            print(f"  {status_icon} Step {i+1}: [{s['intent']}] "
                  f"${s['cost_usd']}  {s['output'][:80]}...")
    except Exception as e:
        print(f"{FAIL} {e}")
        errors.append(("plan workflow", str(e)))

    # ── 4. Approval gate ──────────────────────────────────────────────
    section("4. Approval gate (pause + approve + resume)")
    try:
        orch_gated = OrchestratorAgent(config={
            "trust_layer": {"auto_approve": False},
            "constraints": {"max_tokens": 50_000, "max_cost": 1.00},
        })
        await orch_gated.initialize()
        r = await orch_gated.orchestrate("Send cold outreach to 50 leads")
        assert r.get("approval"), f"Expected approval pause, got: {r.get('status')}"
        aid = r["approval"]["id"]
        print(f"{PASS} Paused with approval_id={aid}")
        pending = orch_gated.approval_manager.list_pending()
        assert len(pending) == 1
        print(f"{PASS} Pending queue: {len(pending)}")

        resumed = await orch_gated.decide_approval(aid, approved=True)
        assert resumed["success"], f"Resume failed: {resumed.get('error')}"
        print(f"{PASS} Resumed: success={resumed['success']}")
        print(f"{PASS} Output:  {resumed['output'][:150]}...")
        await orch_gated.shutdown()
    except Exception as e:
        print(f"{FAIL} {e}")
        errors.append(("approval gate", str(e)))

    # ── 5. Persistence & stats ────────────────────────────────────────
    section("5. Persistence (runs + stats)")
    try:
        runs = await orch.list_runs()
        stats = await orch.get_reliability_stats()
        assert stats["total_runs"] >= 1
        print(f"{PASS} Runs recorded:  {stats['total_runs']}")
        print(f"{PASS} Success rate:   {stats['success_rate']:.0%}")
        print(f"{PASS} Verified runs:  {stats['verified_runs']}")
        print(f"{PASS} Full stats: {json.dumps(stats, indent=2)}")
    except Exception as e:
        print(f"{FAIL} {e}")
        errors.append(("persistence", str(e)))

    # ── Summary ───────────────────────────────────────────────────────
    await orch.shutdown()
    elapsed = time.time() - t0

    section("Summary")
    total = 5
    passed = total - len(errors)
    print(f"  {passed}/{total} checks passed in {elapsed:.1f}s")
    if errors:
        for name, err in errors:
            print(f"  {FAIL} {name}: {err}")
        sys.exit(1)
    else:
        constraints = orch.constraint_engine.get_status()
        cost = next((c for c in constraints if c["name"] == "cost_budget"), {})
        print(f"  Total cost: ${cost.get('used', '?')}")
        print(f"\n  {PASS} All checks passed!")


if __name__ == "__main__":
    asyncio.run(main())
