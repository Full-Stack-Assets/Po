"""
FastAPI REST API server for the Orchestration System.
Run: uvicorn orchestrator_agent.server:app --reload
"""

from __future__ import annotations
from typing import Any, List, Optional
import json
import logging
import os
import time

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from orchestrator_agent.models import ExecutionMode
from orchestrator_agent.orchestrator import OrchestratorAgent
from orchestrator_agent.tools import default_tool_registry
from orchestrator_agent.scheduler import WorkflowScheduler
from orchestrator_agent.auth import (
    AuthManager, InMemoryUserStore, User, auth_dependency,
)
from orchestrator_agent.conversations import (
    InMemoryConversationStore, MessageRole,
)
from orchestrator_agent.analytics import AnalyticsEngine, metrics_to_dict
from orchestrator_agent.config_api import ConfigManager, config_to_dict

logger = logging.getLogger(__name__)

PO_ENV = os.environ.get("PO_ENV", "development")
PO_API_KEY = os.environ.get("PO_API_KEY", "")
PO_JWT_SECRET = os.environ.get("PO_JWT_SECRET", "po-dev-secret-change-me")
CORS_ORIGINS = os.environ.get("PO_CORS_ORIGINS", "*").split(",")
AUTH_ENABLED = os.environ.get("PO_AUTH_ENABLED", "").lower() in ("1", "true", "yes")

app = FastAPI(
    title="Po — AI Growth Operator API",
    description="Multi-provider agent orchestration with trust layer",
    version="3.0.0",
    docs_url="/docs" if PO_ENV != "production" else None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

PUBLIC_PATHS = {"/v2/health", "/v2/auth/register", "/v2/auth/login",
                "/docs", "/openapi.json"}


@app.middleware("http")
async def auth_and_logging(request: Request, call_next):
    start = time.time()

    if PO_API_KEY and request.url.path not in PUBLIC_PATHS:
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        api_key = request.headers.get("X-API-Key", "")
        if not AUTH_ENABLED and token != PO_API_KEY and api_key != PO_API_KEY:
            return JSONResponse({"error": "unauthorized"}, status_code=401)

    response = await call_next(request)

    if PO_ENV == "production":
        ms = (time.time() - start) * 1000
        logger.info(f"{request.method} {request.url.path} "
                     f"{response.status_code} {ms:.0f}ms")

    return response


orchestrator = OrchestratorAgent()
tool_registry = None
scheduler = None
auth_manager = None
conversation_store = None
analytics_engine = None
config_manager = None


@app.on_event("startup")
async def startup():
    global tool_registry, scheduler, auth_manager
    global conversation_store, analytics_engine, config_manager

    if PO_ENV == "production":
        logging.basicConfig(level=logging.INFO,
                            format="%(asctime)s %(levelname)s %(message)s")
    await orchestrator.initialize()
    tool_registry = default_tool_registry(orchestrator.llm)
    scheduler = WorkflowScheduler(orchestrator)

    user_store = InMemoryUserStore()
    auth_manager = AuthManager(PO_JWT_SECRET, user_store)
    app.state.auth_manager = auth_manager

    conversation_store = InMemoryConversationStore()
    analytics_engine = AnalyticsEngine(
        orchestrator.store, orchestrator.llm, orchestrator.approval_manager)
    config_manager = ConfigManager(orchestrator)

    logger.info(f"Po API ready (env={PO_ENV}, auth={AUTH_ENABLED})")


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


class RegisterRequest(BaseModel):
    email: str
    password: str
    name: str = ""


class LoginRequest(BaseModel):
    email: str
    password: str


class ConversationCreateRequest(BaseModel):
    title: Optional[str] = None


class MessageRequest(BaseModel):
    content: str
    validate_idea: Optional[bool] = Field(default=False, alias="validate")
    model_config = ConfigDict(populate_by_name=True)


class ConstraintUpdateRequest(BaseModel):
    max_tokens: Optional[int] = None
    max_cost: Optional[float] = None


class TrustUpdateRequest(BaseModel):
    auto_approve: Optional[bool] = None
    live_signals: Optional[bool] = None
    fail_on_unverified: Optional[bool] = None


# ── Auth ────────────────────────────────────────────────────────────

@app.post("/v2/auth/register")
async def register(req: RegisterRequest):
    try:
        user = await auth_manager.register(req.email, req.password, req.name)
        tokens = await auth_manager.login(req.email, req.password)
        return {
            "user": {"id": user.id, "email": user.email, "name": user.name},
            "access_token": tokens["access_token"],
            "token_type": "bearer",
        }
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post("/v2/auth/login")
async def login(req: LoginRequest):
    try:
        result = await auth_manager.login(req.email, req.password)
        return result
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=401)


@app.get("/v2/auth/me")
async def get_me(user: User = Depends(auth_dependency)):
    return {"id": user.id, "email": user.email, "name": user.name,
            "created_at": user.created_at.isoformat(),
            "settings": user.settings}


@app.post("/v2/auth/api-keys")
async def create_api_key(user: User = Depends(auth_dependency)):
    key = await auth_manager.user_store.create_api_key(user.id)
    return {"api_key": key}


@app.delete("/v2/auth/api-keys/{key}")
async def revoke_api_key(key: str, user: User = Depends(auth_dependency)):
    ok = await auth_manager.user_store.revoke_api_key(user.id, key)
    return {"revoked": ok}


# ── Conversations ───────────────────────────────────────────────────

@app.post("/v2/conversations")
async def create_conversation(req: ConversationCreateRequest):
    user_id = "default"
    conv = await conversation_store.create(user_id, req.title)
    return {"id": conv.id, "title": conv.title, "created_at": conv.created_at}


@app.get("/v2/conversations")
async def list_conversations(limit: int = 20, offset: int = 0):
    user_id = "default"
    convs = await conversation_store.list_for_user(user_id, limit, offset)
    return {"conversations": [
        {"id": c.id, "title": c.title, "created_at": c.created_at,
         "updated_at": c.updated_at, "status": c.status,
         "metadata": c.metadata}
        for c in convs
    ]}


@app.get("/v2/conversations/{conversation_id}")
async def get_conversation(conversation_id: str):
    conv = await conversation_store.get(conversation_id)
    if not conv:
        return JSONResponse({"error": "not found"}, status_code=404)
    return {
        "id": conv.id, "title": conv.title, "user_id": conv.user_id,
        "created_at": conv.created_at, "updated_at": conv.updated_at,
        "status": conv.status, "metadata": conv.metadata,
        "messages": [
            {"id": m.id, "role": m.role.value, "content": m.content,
             "timestamp": m.timestamp, "metadata": m.metadata}
            for m in conv.messages
        ],
    }


@app.get("/v2/conversations/{conversation_id}/messages")
async def get_messages(conversation_id: str, limit: int = 50,
                       before: Optional[str] = None):
    msgs = await conversation_store.get_messages(conversation_id, limit, before)
    return {"messages": [
        {"id": m.id, "role": m.role.value, "content": m.content,
         "timestamp": m.timestamp, "metadata": m.metadata}
        for m in msgs
    ]}


@app.post("/v2/conversations/{conversation_id}/messages")
async def send_message(conversation_id: str, req: MessageRequest):
    conv = await conversation_store.get(conversation_id)
    if not conv:
        return JSONResponse({"error": "conversation not found"}, status_code=404)

    user_msg = await conversation_store.add_message(
        conversation_id, MessageRole.USER, req.content)

    mode = ExecutionMode.SEQUENTIAL
    result = await orchestrator.orchestrate(
        req.content, conversation_id, mode,
        validate=bool(req.validate_idea),
    )

    result_meta = {}
    if isinstance(result, dict):
        result_meta = {
            "intent": result.get("intent"),
            "model_used": result.get("model_used"),
            "provider_used": result.get("provider_used"),
            "cost_usd": result.get("cost_usd", 0),
            "tokens_used": result.get("tokens_used", 0),
            "latency_ms": result.get("latency_ms", 0),
            "success": result.get("success"),
            "validation": result.get("validation"),
            "verification": result.get("verification"),
        }
        output = result.get("output", "")
    else:
        output = str(result)

    assistant_msg = await conversation_store.add_message(
        conversation_id, MessageRole.ASSISTANT, output, result_meta)

    return {
        "user_message": {"id": user_msg.id, "role": "user",
                         "content": user_msg.content,
                         "timestamp": user_msg.timestamp},
        "assistant_message": {"id": assistant_msg.id, "role": "assistant",
                              "content": assistant_msg.content,
                              "timestamp": assistant_msg.timestamp,
                              "metadata": assistant_msg.metadata},
        "result": result,
    }


@app.delete("/v2/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str):
    ok = await conversation_store.delete(conversation_id)
    return {"deleted": ok}


@app.post("/v2/conversations/{conversation_id}/archive")
async def archive_conversation(conversation_id: str):
    ok = await conversation_store.archive(conversation_id)
    return {"archived": ok}


# ── Analytics ───────────────────────────────────────────────────────

@app.get("/v2/analytics/dashboard")
async def analytics_dashboard(period_hours: int = 24):
    metrics = await analytics_engine.get_dashboard(period_hours)
    return metrics_to_dict(metrics)


@app.get("/v2/analytics/cost-timeseries")
async def analytics_cost_ts(period_hours: int = 24, bucket: str = "hour"):
    points = await analytics_engine.get_cost_timeseries(period_hours, bucket)
    return {"data": [{"timestamp": p.timestamp, "value": p.value,
                       "label": p.label} for p in points]}


@app.get("/v2/analytics/runs-timeseries")
async def analytics_runs_ts(period_hours: int = 24, bucket: str = "hour"):
    points = await analytics_engine.get_runs_timeseries(period_hours, bucket)
    return {"data": [{"timestamp": p.timestamp, "value": p.value,
                       "label": p.label} for p in points]}


@app.get("/v2/analytics/cost-by-provider")
async def analytics_cost_provider(period_hours: int = 24):
    breakdown = await analytics_engine.get_cost_by_provider(period_hours)
    return {"data": [{"provider": b.provider, "model": b.model,
                       "cost_usd": b.cost_usd, "token_count": b.token_count,
                       "run_count": b.run_count} for b in breakdown]}


@app.get("/v2/analytics/cost-by-intent")
async def analytics_cost_intent(period_hours: int = 24):
    breakdown = await analytics_engine.get_cost_by_intent(period_hours)
    return {"data": [{"provider": b.provider, "model": b.model,
                       "cost_usd": b.cost_usd, "token_count": b.token_count,
                       "run_count": b.run_count} for b in breakdown]}


@app.get("/v2/analytics/providers")
async def analytics_providers():
    providers = await analytics_engine.get_provider_leaderboard()
    return {"data": [{"provider": p.provider, "total_requests": p.total_requests,
                       "success_count": p.success_count,
                       "failure_count": p.failure_count,
                       "avg_latency_ms": p.avg_latency_ms,
                       "total_cost_usd": p.total_cost_usd,
                       "circuit_open": p.circuit_open} for p in providers]}


# ── Config ──────────────────────────────────────────────────────────

@app.get("/v2/config")
async def get_config():
    cfg = await config_manager.get_config()
    return config_to_dict(cfg)


@app.put("/v2/config/constraints")
async def update_constraints(req: ConstraintUpdateRequest):
    constraints = await config_manager.update_constraints(
        max_tokens=req.max_tokens, max_cost=req.max_cost)
    return {"constraints": [
        {"name": c.name, "current_used": c.current_used,
         "max_value": c.max_value, "unit": c.unit}
        for c in constraints
    ]}


@app.put("/v2/config/trust")
async def update_trust(req: TrustUpdateRequest):
    kwargs = {k: v for k, v in req.model_dump().items() if v is not None}
    settings = await config_manager.update_trust_settings(**kwargs)
    return {"trust": {
        "auto_approve": settings.auto_approve,
        "live_signals": settings.live_signals,
        "fail_on_unverified": settings.fail_on_unverified,
        "approval_ttl_seconds": settings.approval_ttl_seconds,
        "validation_threshold": settings.validation_threshold,
    }}


@app.post("/v2/config/providers/{provider}/test")
async def test_provider(provider: str):
    result = await config_manager.test_provider(provider)
    return result


@app.post("/v2/config/providers/{provider}/reset")
async def reset_provider_circuit(provider: str):
    ok = await config_manager.reset_provider_circuit(provider)
    return {"reset": ok}


@app.post("/v2/config/budgets/reset")
async def reset_budgets():
    constraints = await config_manager.reset_budgets()
    return {"constraints": [
        {"name": c.name, "current_used": c.current_used,
         "max_value": c.max_value, "unit": c.unit}
        for c in constraints
    ]}


@app.get("/v2/config/providers/{provider}/models")
async def get_provider_models(provider: str):
    models = await config_manager.get_provider_models(provider)
    return {"models": models}


# ── Orchestration ───────────────────────────────────────────────────

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
