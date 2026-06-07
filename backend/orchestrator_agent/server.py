"""
FastAPI REST API server for the Orchestration System.
Run: uvicorn orchestrator_agent.server:app --reload
"""

from __future__ import annotations
from typing import List, Optional
import json

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from orchestrator_agent.models import ExecutionMode
from orchestrator_agent.orchestrator import OrchestratorAgent

app = FastAPI(
    title="Constraint-Optimized LLM Agent Orchestrator",
    description="Multi-provider agent orchestration API",
    version="2.0.0",
)

orchestrator = OrchestratorAgent()


@app.on_event("startup")
async def startup():
    await orchestrator.initialize()


@app.on_event("shutdown")
async def shutdown():
    await orchestrator.shutdown()


class OrchestrationRequest(BaseModel):
    input: str
    conversation_id: Optional[str] = ""
    mode: Optional[str] = "sequential"
    stream: Optional[bool] = False
    validate: Optional[bool] = False
    validation_override: Optional[bool] = False


class BatchRequest(BaseModel):
    inputs: List[str]
    conversation_id: Optional[str] = ""
    mode: Optional[str] = "concurrent"


class ApprovalDecisionRequest(BaseModel):
    approved: bool = True
    edited_input: Optional[str] = None
    conversation_id: Optional[str] = ""


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
        validate=bool(req.validate),
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
