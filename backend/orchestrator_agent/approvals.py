"""
Human-in-the-Loop Approval Gates — approvals.py
===============================================

Po's third differentiator: you approve anything risky from your phone.

Safe, reversible actions (research, analysis, summarization) run automatically.
High-blast-radius actions (outreach, spend, public posts, deletions, deploys)
are gated: the pipeline pauses, an ``ApprovalRequest`` is queued, and execution
only resumes once a human approves (optionally editing the payload) or rejects.

This is the synchronous, in-memory analogue of the plan's LangGraph
``interrupt()`` + checkpointer pattern: ``ApprovalManager`` persists pending
requests, enforces a TTL (stale requests auto-expire), and the pipeline exposes
a resume path keyed by ``approval_id``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional
import logging
import uuid

logger = logging.getLogger(__name__)


class ApprovalDecision(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EDITED = "edited"
    EXPIRED = "expired"


class ApprovalType(Enum):
    OUTREACH = "outreach"
    SPEND = "spend"
    PUBLIC_POST = "public_post"
    DELETION = "deletion"
    DEPLOY = "deploy"
    GENERIC = "generic"


@dataclass
class ApprovalRequest:
    """A queued request for human approval of a high-stakes action."""
    type: ApprovalType = ApprovalType.GENERIC
    summary: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    approval_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    status: ApprovalDecision = ApprovalDecision.PENDING
    edited_payload: Optional[Dict[str, Any]] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None
    decided_at: Optional[datetime] = None

    @property
    def is_pending(self) -> bool:
        return self.status == ApprovalDecision.PENDING

    @property
    def is_approved(self) -> bool:
        return self.status in (ApprovalDecision.APPROVED, ApprovalDecision.EDITED)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "type": self.type.value,
            "summary": self.summary,
            "status": self.status.value,
            "payload": self.payload,
            "edited_payload": self.edited_payload,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "decided_at": self.decided_at.isoformat() if self.decided_at else None,
        }


class ApprovalPolicy:
    """Decides whether a task's action needs human approval."""

    # Intent -> approval type for gated (high-blast-radius) intents.
    DEFAULT_GATED = {
        "write": ApprovalType.OUTREACH,   # cold outreach / public copy
        "code": ApprovalType.DEPLOY,      # may deploy / ship code
    }

    def __init__(self, gated: Optional[Dict[str, ApprovalType]] = None):
        self.gated = gated if gated is not None else dict(self.DEFAULT_GATED)

    def requires_approval(self, task: Any) -> Optional[ApprovalType]:
        return self.gated.get(getattr(task, "intent", ""))


class ApprovalManager:
    """In-memory queue + lifecycle for approval requests."""

    def __init__(
        self,
        policy: Optional[ApprovalPolicy] = None,
        *,
        auto_approve: bool = False,
        ttl_seconds: int = 86_400,
    ):
        self.policy = policy or ApprovalPolicy()
        self.auto_approve = auto_approve
        self.ttl_seconds = ttl_seconds
        self._store: Dict[str, ApprovalRequest] = {}

    def create(
        self,
        type: ApprovalType,
        summary: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> ApprovalRequest:
        req = ApprovalRequest(
            type=type,
            summary=summary,
            payload=payload or {},
            expires_at=(datetime.utcnow() + timedelta(seconds=self.ttl_seconds)
                        if self.ttl_seconds else None),
        )
        self._store[req.approval_id] = req
        logger.info(f"Approval queued: {req.approval_id} ({type.value})")
        return req

    def get(self, approval_id: str) -> Optional[ApprovalRequest]:
        req = self._store.get(approval_id)
        if req:
            self._maybe_expire(req)
        return req

    def list_pending(self) -> List[ApprovalRequest]:
        for req in self._store.values():
            self._maybe_expire(req)
        return [r for r in self._store.values() if r.is_pending]

    def decide(
        self,
        approval_id: str,
        decision: ApprovalDecision,
        edited_payload: Optional[Dict[str, Any]] = None,
    ) -> Optional[ApprovalRequest]:
        req = self.get(approval_id)
        if req is None or not req.is_pending:
            return req
        req.status = decision
        req.decided_at = datetime.utcnow()
        if edited_payload is not None:
            req.edited_payload = edited_payload
            req.status = ApprovalDecision.EDITED
        logger.info(f"Approval {approval_id} -> {req.status.value}")
        return req

    def _maybe_expire(self, req: ApprovalRequest) -> None:
        if (req.is_pending and req.expires_at
                and datetime.utcnow() > req.expires_at):
            req.status = ApprovalDecision.EXPIRED
            req.decided_at = datetime.utcnow()
            logger.info(f"Approval {req.approval_id} expired")
