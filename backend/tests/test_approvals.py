"""Unit tests for human-in-the-loop approval gates."""

from datetime import datetime, timedelta

import pytest

from orchestrator_agent.approvals import (
    ApprovalManager, ApprovalPolicy, ApprovalDecision, ApprovalType,
)
from orchestrator_agent.models import Task


def test_policy_gates_risky_intents_only():
    policy = ApprovalPolicy()
    assert policy.requires_approval(Task(intent="write")) == ApprovalType.OUTREACH
    assert policy.requires_approval(Task(intent="code")) == ApprovalType.DEPLOY
    assert policy.requires_approval(Task(intent="research")) is None
    assert policy.requires_approval(Task(intent="summarize")) is None


def test_create_and_list_pending():
    mgr = ApprovalManager()
    req = mgr.create(ApprovalType.SPEND, "increase ad budget", {"amount": 50})
    assert req.is_pending
    pending = mgr.list_pending()
    assert len(pending) == 1
    assert pending[0].approval_id == req.approval_id


def test_approve_decision():
    mgr = ApprovalManager()
    req = mgr.create(ApprovalType.OUTREACH, "send cold email")
    decided = mgr.decide(req.approval_id, ApprovalDecision.APPROVED)
    assert decided.status == ApprovalDecision.APPROVED
    assert decided.is_approved is True
    assert mgr.list_pending() == []


def test_edit_sets_edited_status_and_payload():
    mgr = ApprovalManager()
    req = mgr.create(ApprovalType.OUTREACH, "send cold email",
                     {"body": "original"})
    decided = mgr.decide(req.approval_id, ApprovalDecision.APPROVED,
                         edited_payload={"body": "edited"})
    assert decided.status == ApprovalDecision.EDITED
    assert decided.edited_payload == {"body": "edited"}
    assert decided.is_approved is True


def test_reject_decision():
    mgr = ApprovalManager()
    req = mgr.create(ApprovalType.DELETION, "delete records")
    decided = mgr.decide(req.approval_id, ApprovalDecision.REJECTED)
    assert decided.status == ApprovalDecision.REJECTED
    assert decided.is_approved is False


def test_stale_requests_auto_expire():
    mgr = ApprovalManager(ttl_seconds=1)
    req = mgr.create(ApprovalType.GENERIC, "do thing")
    # Force the expiry into the past.
    req.expires_at = datetime.utcnow() - timedelta(seconds=5)
    fetched = mgr.get(req.approval_id)
    assert fetched.status == ApprovalDecision.EXPIRED
    assert mgr.list_pending() == []


def test_decide_unknown_returns_none():
    mgr = ApprovalManager()
    assert mgr.decide("nope", ApprovalDecision.APPROVED) is None
