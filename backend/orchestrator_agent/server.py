"""
FastAPI REST API server for the Orchestration System.
Run: uvicorn orchestrator_agent.server:app --reload
"""

from __future__ import annotations
from typing import Any, List, Optional
import json

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from orchestrator_agent.models import ExecutionMode
from orchestrator_agent.orchestrator import OrchestratorAgent
from orchestrator_agent.tools import default_tool_registry, ToolResult
from orchestrator_agent.scheduler import WorkflowScheduler

app = FastAPI(
    title="Constraint-Optimized LLM Agent Orchestrator",
    description="Multi-provider agent orchestration API",
    version="2.0.0",
)

# Allow the static web dashboard (served from a different origin/port) to
# call the API in development. Tighten allow_origins for production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

orchestrator = OrchestratorAgent()
tool_registry = None
scheduler = None


@app.on_event("startup")
async def startup():
    global tool_registry, scheduler
    await orchestrator.initialize()
    tool_registry = default_tool_registry(orchestrator.llm)
    scheduler = WorkflowScheduler(orchestrator)


@app.on_event("shutdown")
async def shutdown():
    if scheduler:
        await scheduler.stop()
    await orchestrator.shutdown()


class OrchestrationRequest(BaseModel):
    # populate_by_name lets the JSON key stay "validate" while the Python
    # attribute is "validate_idea" (avoids shadowing BaseModel.validate).
    model_config = ConfigDict(populate_by_name=True)

    input: str
    conversation_id: Optional[str] = ""
    mode: Optional[str] = "sequential"
    stream: Optional[bool] = False
    validate_idea: Optional[bool] = Field(default=False, alias="validate")
    validation_override: Optional[bool] = False


class BatchRequest(BaseModel):
    inputs: List[str]
    conversation_id: Optional[str] = ""
    mode: Optional[str] = "concurrent"


class ApprovalDecisionRequest(BaseModel):
    approved: bool = True
    edited_input: Optional[str] = None
    conversation_id: Optional[str] = ""


class WorkflowRequest(BaseModel):
    steps: List[Any]
    conversation_id: Optional[str] = ""
    thread_id: Optional[str] = None
    default_intent: Optional[str] = None


class WorkflowPlanRequest(BaseModel):
    goal: str
    conversation_id: Optional[str] = ""
    thread_id: Optional[str] = None


class WorkflowResumeRequest(BaseModel):
    conversation_id: Optional[str] = ""


class ToolExecuteRequest(BaseModel):
    tool: str
    params: dict = {}


class ScheduleRequest(BaseModel):
    name: str
    goal: str
    interval_seconds: int = 3600
    max_runs: Optional[int] = None


@app.post("/v2/orchestrate")
async def orchestrate(req: OrchestrationRequest):
    if req.stream:
        async def generate():
            async for token in orchestrator.stream_orchestrate(
                req.input, req.conversation_id or ""
            ):
                yield f"data: {json.dumps({'token': token})}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(generate(), media_type="text/event-stream")

    mode = ExecutionMode(req.mode) if req.mode else ExecutionMode.SEQUENTIAL
    return await orchestrator.orchestrate(
        req.input, req.conversation_id or "", mode,
        validate=bool(req.validate_idea),
        validation_override=bool(req.validation_override),
    )


@app.post("/v2/batch")
async def batch(req: BatchRequest):
    mode = ExecutionMode(req.mode) if req.mode else ExecutionMode.CONCURRENT
    return await orchestrator.orchestrate_batch(
        req.inputs, req.conversation_id or "", mode
    )


@app.get("/v2/approvals")
async def list_approvals():
    """List pending human-in-the-loop approval requests."""
    if orchestrator.approval_manager is None:
        return {"approvals": []}
    return {
        "approvals": [r.to_dict()
                      for r in orchestrator.approval_manager.list_pending()]
    }


@app.post("/v2/approvals/{approval_id}")
async def decide_approval(approval_id: str, req: ApprovalDecisionRequest):
    """Approve / reject / edit a pending action and resume the task."""
    return await orchestrator.decide_approval(
        approval_id, approved=req.approved,
        edited_input=req.edited_input,
        conversation_id=req.conversation_id or "",
    )


@app.post("/v2/workflows/plan")
async def plan_workflow(req: WorkflowPlanRequest):
    """Auto-generate and run a workflow from a high-level goal."""
    return await orchestrator.plan_and_run_workflow(
        req.goal, req.conversation_id or "", req.thread_id)


@app.post("/v2/workflows")
async def start_workflow(req: WorkflowRequest):
    """Run a checkpointed multi-step workflow."""
    return await orchestrator.run_workflow(
        req.steps, req.conversation_id or "", req.thread_id, req.default_intent)


@app.post("/v2/workflows/{thread_id}/resume")
async def resume_workflow(thread_id: str, req: WorkflowResumeRequest):
    """Resume a paused/failed/interrupted workflow from its checkpoint."""
    return await orchestrator.resume_workflow(
        thread_id, req.conversation_id or "")


@app.get("/v2/workflows/{thread_id}")
async def get_workflow(thread_id: str):
    state = await orchestrator.get_workflow(thread_id)
    return state or {"error": f"no workflow '{thread_id}'"}


@app.get("/v2/runs")
async def runs(limit: int = 50):
    """Recent orchestration runs (persisted audit trail)."""
    return {"runs": await orchestrator.list_runs(limit)}


@app.get("/v2/stats")
async def stats():
    """Aggregate reliability metrics for the public dashboard."""
    return await orchestrator.get_reliability_stats()


@app.get("/v2/status")
async def status():
    return orchestrator.get_status()


@app.get("/v2/models")
async def models():
    return orchestrator.llm.get_available_models()


@app.get("/v2/health")
async def health():
    return {
        "status": "healthy" if orchestrator._initialized else "initializing",
        "providers": orchestrator.llm.get_health(),
        "usage": orchestrator.llm.get_usage(),
    }


# ── Tools ────────────────────────────────────────────────────────────

@app.get("/v2/tools")
async def list_tools():
    """List available action tools."""
    return {"tools": tool_registry.list_tools() if tool_registry else []}


@app.post("/v2/tools/execute")
async def execute_tool(req: ToolExecuteRequest):
    """Execute an action tool by name."""
    if not tool_registry:
        return {"success": False, "error": "Tools not initialized"}
    result = await tool_registry.execute(req.tool, req.params)
    return {
        "tool": result.tool,
        "success": result.success,
        "output": result.output,
        "data": result.data,
        "error": result.error,
        "verify_actions": result.verify_actions,
        "cost_usd": result.cost_usd,
        "latency_ms": result.latency_ms,
    }


# ── Scheduler ────────────────────────────────────────────────────────

@app.get("/v2/schedules")
async def list_schedules():
    """List scheduled workflows."""
    return {"schedules": scheduler.list_schedules() if scheduler else []}


@app.post("/v2/schedules")
async def create_schedule(req: ScheduleRequest):
    """Schedule a recurring workflow."""
    if not scheduler:
        return {"error": "Scheduler not initialized"}
    entry = scheduler.schedule(
        req.name, req.goal, req.interval_seconds, req.max_runs)
    return entry.to_dict()


@app.post("/v2/schedules/{schedule_id}/run")
async def run_schedule_now(schedule_id: str):
    """Trigger a scheduled workflow immediately."""
    if not scheduler:
        return {"error": "Scheduler not initialized"}
    return await scheduler.run_immediate(schedule_id)


@app.post("/v2/schedules/{schedule_id}/pause")
async def pause_schedule(schedule_id: str):
    """Pause a scheduled workflow."""
    if not scheduler:
        return {"error": "Scheduler not initialized"}
    return {"paused": scheduler.pause(schedule_id)}


@app.post("/v2/schedules/{schedule_id}/resume")
async def resume_schedule(schedule_id: str):
    """Resume a paused scheduled workflow."""
    if not scheduler:
        return {"error": "Scheduler not initialized"}
    return {"resumed": scheduler.resume(schedule_id)}


@app.delete("/v2/schedules/{schedule_id}")
async def cancel_schedule(schedule_id: str):
    """Cancel a scheduled workflow."""
    if not scheduler:
        return {"error": "Scheduler not initialized"}
    return {"cancelled": scheduler.cancel(schedule_id)}


@app.post("/v2/scheduler/start")
async def start_scheduler():
    """Start the background scheduler."""
    if not scheduler:
        return {"error": "Scheduler not initialized"}
    await scheduler.start()
    return {"status": "started", "schedules": len(scheduler.list_schedules())}


@app.post("/v2/scheduler/stop")
async def stop_scheduler():
    """Stop the background scheduler."""
    if not scheduler:
        return {"error": "Scheduler not initialized"}
    await scheduler.stop()
    return {"status": "stopped"}


@app.get("/v2/digest")
async def digest(period_hours: int = 24):
    """Generate a digest report of recent activity."""
    if not scheduler:
        return {"error": "Scheduler not initialized"}
    report = await scheduler.generate_digest(period_hours)
    return report.to_dict()
