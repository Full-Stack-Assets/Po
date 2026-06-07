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
