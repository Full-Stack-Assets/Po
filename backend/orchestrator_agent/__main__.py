"""
Interactive CLI for testing the orchestrator.
Usage: python -m orchestrator_agent
"""

import asyncio
import json
import sys

from orchestrator_agent.orchestrator import OrchestratorAgent


async def main():
    print("=" * 60)
    print("  Constraint-Optimized LLM Agent Orchestrator v2")
    print("=" * 60)

    orch = OrchestratorAgent(config={
        "constraints": {"max_tokens": 200_000, "max_cost": 10.00}
    })

    try:
        await orch.initialize()
    except RuntimeError as e:
        print(f"\nError: {e}")
        sys.exit(1)

    status = orch.get_status()
    active = len([p for p in status["providers"] if not p["circuit_open"]])
    print(f"\nProviders active: {active}")
    print(f"Agents registered: {len(status['agents'])}")
    print(f"Models available: {len(status['models'])}")
    print("\nType your request (or 'quit' to exit, 'status' for stats):\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            break
        if user_input.lower() == "status":
            print(json.dumps(orch.get_status(), indent=2))
            continue

        result = await orch.orchestrate(user_input)
        print(f"\n[{result['provider_used']}/{result['model_used']}] "
              f"(intent={result['intent']}, "
              f"tokens={result['tokens_used']}, "
              f"cost=${result['cost_usd']}, "
              f"latency={result['latency_ms']}ms)")
        print(f"\n{result['output']}\n")

    await orch.shutdown()
    print("\nFinal usage:", orch.llm.get_usage())


if __name__ == "__main__":
    asyncio.run(main())
