"""
Interactive CLI for the Po AI Operator.
Usage: python -m orchestrator_agent
"""

from __future__ import annotations

import asyncio
import os
import sys

from orchestrator_agent.orchestrator import OrchestratorAgent


# ── Terminal colors ──────────────────────────────────────────────────

class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    MAGENTA = "\033[95m"
    BLUE = "\033[94m"
    WHITE = "\033[97m"


def _bar(used: float, total: float, width: int = 20) -> str:
    if total <= 0:
        return "░" * width
    pct = min(used / total, 1.0)
    filled = int(pct * width)
    color = C.GREEN if pct < 0.6 else C.YELLOW if pct < 0.85 else C.RED
    return f"{color}{'█' * filled}{'░' * (width - filled)}{C.RESET}"


def _format_cost(cost: float) -> str:
    if cost < 0.001:
        return f"${cost:.6f}"
    return f"${cost:.4f}"


def _header():
    print(f"""
{C.MAGENTA}{C.BOLD}╔══════════════════════════════════════════════════════════╗
║                 Po — AI Growth Operator                  ║
║            Trust · Validate · Verify · Prove             ║
╚══════════════════════════════════════════════════════════╝{C.RESET}
""")


def _show_providers(status: dict):
    providers = status.get("providers", [])
    active = [p for p in providers if not p.get("circuit_open")]
    down = [p for p in providers if p.get("circuit_open")]
    print(f"  {C.BOLD}Providers:{C.RESET} ", end="")
    for p in active:
        print(f"{C.GREEN}●{C.RESET} {p['provider']} ", end="")
    for p in down:
        print(f"{C.RED}○{C.RESET} {p['provider']} ", end="")
    if not providers:
        print(f"{C.RED}none{C.RESET}", end="")
    print()


def _show_agents(status: dict):
    agents = status.get("agents", [])
    print(f"  {C.BOLD}Agents:{C.RESET}    ", end="")
    names = [a["name"] for a in agents]
    print(f"{C.DIM}{', '.join(names)}{C.RESET}")


def _show_constraints(status: dict):
    constraints = status.get("constraints", [])
    for c in constraints:
        name = c["name"].replace("_", " ").title()
        bar = _bar(c["used"], c["max"])
        unit = c.get("unit", "")
        if unit == "USD":
            label = f"{_format_cost(c['used'])} / {_format_cost(c['max'])}"
        else:
            label = f"{c['used']:,.0f} / {c['max']:,.0f} {unit}"
        print(f"  {bar}  {name}: {label}")


def _show_result(result: dict):
    success = result.get("success", False)
    icon = f"{C.GREEN}✓{C.RESET}" if success else f"{C.RED}✗{C.RESET}"
    intent = result.get("intent", "?")
    model = result.get("model_used", "?")
    provider = result.get("provider_used", "?")
    cost = result.get("cost_usd", 0)
    tokens = result.get("tokens_used", 0)
    latency = result.get("latency_ms", 0)

    print(f"\n  {icon} {C.BOLD}{intent}{C.RESET} via "
          f"{C.CYAN}{provider}/{model}{C.RESET}")
    print(f"  {C.DIM}tokens={tokens:,}  cost={_format_cost(cost)}  "
          f"latency={latency:.0f}ms{C.RESET}")

    validation = result.get("validation")
    if validation:
        score = validation.get("overall_score", 0)
        rating = validation.get("score", "?")
        color = (C.GREEN if rating == "green" else
                 C.YELLOW if rating == "yellow" else C.RED)
        print(f"  {C.BOLD}Validation:{C.RESET} {color}{rating} "
              f"({score}/100){C.RESET}")

    verification = result.get("verification")
    if verification:
        p, f_ = verification.get("passed", 0), verification.get("failed", 0)
        color = C.GREEN if f_ == 0 else C.RED
        print(f"  {C.BOLD}Verification:{C.RESET} {color}{p} passed, "
              f"{f_} failed{C.RESET}")
        if result.get("refunded"):
            print(f"  {C.YELLOW}⟲ Auto-refunded{C.RESET}")

    approval = result.get("approval")
    if approval:
        print(f"  {C.YELLOW}⏸ Awaiting approval:{C.RESET} "
              f"{approval.get('type', '?')} (id={approval.get('id', '?')})")

    output = result.get("output", "")
    if output:
        print(f"\n{output}\n")
    elif result.get("error") and result["error"] != "awaiting_approval":
        print(f"\n  {C.RED}Error: {result['error']}{C.RESET}\n")


def _show_workflow_result(result: dict):
    status = result.get("status", "?")
    color = (C.GREEN if status == "completed" else
             C.YELLOW if status == "awaiting_approval" else C.RED)
    print(f"\n  {C.BOLD}Workflow:{C.RESET} {color}{status}{C.RESET}")

    if result.get("plan_raw"):
        print(f"  {C.DIM}Plan: {result['plan_raw'][:120]}...{C.RESET}")

    for i, step in enumerate(result.get("results", [])):
        icon = (f"{C.GREEN}✓{C.RESET}" if step.get("success")
                else f"{C.RED}✗{C.RESET}")
        intent = step.get("intent", "?")
        cost = step.get("cost_usd", 0)
        out = (step.get("output", "") or "")[:80]
        print(f"  {icon} Step {i+1} [{intent}] {_format_cost(cost)}  {out}...")

    if result.get("error"):
        print(f"  {C.RED}Error: {result['error']}{C.RESET}")
    print()


def _help():
    print(f"""
{C.BOLD}Commands:{C.RESET}
  {C.CYAN}<any text>{C.RESET}           Orchestrate a single task
  {C.CYAN}validate <text>{C.RESET}      Validate an idea before execution
  {C.CYAN}plan <goal>{C.RESET}          Auto-plan and execute a workflow
  {C.CYAN}approve <id>{C.RESET}         Approve a pending action
  {C.CYAN}reject <id>{C.RESET}          Reject a pending action
  {C.CYAN}approvals{C.RESET}            List pending approvals
  {C.CYAN}status{C.RESET}               Show system status
  {C.CYAN}stats{C.RESET}                Show reliability metrics
  {C.CYAN}runs{C.RESET}                 Show recent runs
  {C.CYAN}tools{C.RESET}                List available tools
  {C.CYAN}help{C.RESET}                 Show this help
  {C.CYAN}quit{C.RESET}                 Exit
""")


async def main():
    _header()

    config: dict = {
        "constraints": {
            "max_tokens": int(os.environ.get("PO_MAX_TOKENS", 200_000)),
            "max_cost": float(os.environ.get("PO_MAX_COST", 10.00)),
        },
        "trust_layer": {
            "auto_approve": os.environ.get("PO_AUTO_APPROVE", "").lower()
                           not in ("0", "false", "no"),
            "live_signals": os.environ.get("PO_LIVE_SIGNALS", "").lower()
                           in ("1", "true", "yes"),
        },
    }

    orch = OrchestratorAgent(config=config)
    print(f"  {C.DIM}Initializing...{C.RESET}", end="\r")

    try:
        await orch.initialize()
    except RuntimeError as e:
        print(f"\n  {C.RED}Error: {e}{C.RESET}")
        print("\n  Set at least one provider API key in the environment.")
        print(f"  See {C.CYAN}backend/.env.example{C.RESET} for options.\n")
        sys.exit(1)

    status = orch.get_status()
    _show_providers(status)
    _show_agents(status)
    _show_constraints(status)

    auto = config["trust_layer"]["auto_approve"]
    live = config["trust_layer"]["live_signals"]
    print(f"  {C.BOLD}Trust:{C.RESET}     auto_approve={'on' if auto else 'off'}  "
          f"live_signals={'on' if live else 'off'}")
    print(f"\n  Type {C.CYAN}help{C.RESET} for commands.\n")

    while True:
        try:
            raw = input(f"{C.MAGENTA}po ▸{C.RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not raw:
            continue

        cmd = raw.lower()

        if cmd in ("quit", "exit", "q"):
            break

        elif cmd == "help":
            _help()

        elif cmd == "status":
            s = orch.get_status()
            _show_providers(s)
            _show_agents(s)
            _show_constraints(s)

        elif cmd == "stats":
            stats = await orch.get_reliability_stats()
            if stats.get("persistence") == "disabled":
                print(f"  {C.DIM}Persistence disabled (in-memory mode){C.RESET}\n")
            else:
                total = stats.get("total_runs", 0)
                rate = stats.get("success_rate", 0)
                verified = stats.get("verified_runs", 0)
                color = C.GREEN if rate >= 0.9 else C.YELLOW if rate >= 0.7 else C.RED
                print(f"\n  {C.BOLD}Reliability{C.RESET}")
                print(f"  Total runs:    {total}")
                print(f"  Success rate:  {color}{rate:.0%}{C.RESET}")
                print(f"  Verified:      {verified}")
                print(f"  Refunded:      {stats.get('refunded_runs', 0)}\n")

        elif cmd == "runs":
            runs = await orch.list_runs(10)
            if not runs:
                print(f"  {C.DIM}No runs recorded{C.RESET}\n")
            else:
                for r in runs[:10]:
                    icon = (f"{C.GREEN}✓{C.RESET}" if r.get("success")
                            else f"{C.RED}✗{C.RESET}")
                    intent = r.get("intent", "?")
                    cost = _format_cost(r.get("cost_usd", 0))
                    out = (r.get("output", "") or "")[:60]
                    print(f"  {icon} [{intent}] {cost}  {out}")
                print()

        elif cmd == "approvals":
            if not orch.approval_manager:
                print(f"  {C.DIM}Approvals disabled{C.RESET}\n")
            else:
                pending = orch.approval_manager.list_pending()
                if not pending:
                    print(f"  {C.GREEN}No pending approvals{C.RESET}\n")
                else:
                    for req in pending:
                        print(f"  {C.YELLOW}⏸{C.RESET} {req.approval_id}: "
                              f"{req.summary[:80]}")
                        print(f"    {C.DIM}type={req.type.value}  "
                              f"created={req.created_at}{C.RESET}")
                    print(f"\n  Use {C.CYAN}approve <id>{C.RESET} or "
                          f"{C.CYAN}reject <id>{C.RESET}\n")

        elif cmd == "tools":
            from orchestrator_agent.tools import default_tool_registry
            registry = default_tool_registry(orch.llm)
            for t in registry.list_tools():
                print(f"  {C.CYAN}{t['name']}{C.RESET}: {t['description']}")
            print()

        elif cmd.startswith("approve "):
            aid = raw[8:].strip()
            if not aid:
                print(f"  {C.RED}Usage: approve <id>{C.RESET}\n")
                continue
            result = await orch.decide_approval(aid, approved=True)
            _show_result(result)
            _show_constraints(orch.get_status())

        elif cmd.startswith("reject "):
            aid = raw[7:].strip()
            if not aid:
                print(f"  {C.RED}Usage: reject <id>{C.RESET}\n")
                continue
            result = await orch.decide_approval(aid, approved=False)
            _show_result(result)

        elif cmd.startswith("validate "):
            text = raw[9:].strip()
            if not text:
                print(f"  {C.RED}Usage: validate <idea>{C.RESET}\n")
                continue
            result = await orch.orchestrate(text, validate=True)
            _show_result(result)
            _show_constraints(orch.get_status())

        elif cmd.startswith("plan "):
            goal = raw[5:].strip()
            if not goal:
                print(f"  {C.RED}Usage: plan <goal>{C.RESET}\n")
                continue
            print(f"  {C.DIM}Planning and executing...{C.RESET}")
            result = await orch.plan_and_run_workflow(goal)
            _show_workflow_result(result)
            _show_constraints(orch.get_status())

        else:
            result = await orch.orchestrate(raw)
            _show_result(result)
            _show_constraints(orch.get_status())

    await orch.shutdown()
    print(f"\n  {C.DIM}Session ended.{C.RESET}\n")


if __name__ == "__main__":
    asyncio.run(main())
