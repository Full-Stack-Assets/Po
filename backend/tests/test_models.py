"""Unit tests for core data models."""

from orchestrator_agent.models import (
    Constraint, Task, TaskContext, TaskStatus,
)


class TestConstraint:
    def test_consume_within_budget(self):
        c = Constraint(name="tokens", max_value=1000, unit="tokens")
        assert c.consume(500) is True
        assert c.remaining == 500
        assert c.utilization == 0.5

    def test_consume_exceeds_hard_limit(self):
        c = Constraint(name="cost", max_value=1.0, hard_limit=True)
        assert c.consume(0.5) is True
        assert c.consume(0.6) is False  # would exceed
        assert c.current_value == 0.5   # unchanged

    def test_consume_exceeds_soft_limit(self):
        c = Constraint(name="latency", max_value=100, hard_limit=False)
        assert c.consume(150) is True  # soft limit allows it
        assert c.is_exceeded is True

    def test_reset(self):
        c = Constraint(name="tokens", max_value=1000)
        c.consume(500)
        c.reset()
        assert c.current_value == 0
        assert c.remaining == 1000


class TestTaskContext:
    def test_add_and_retrieve_messages(self):
        ctx = TaskContext()
        ctx.add_message("user", "Hello")
        ctx.add_message("assistant", "Hi there", agent_id="agent1")
        assert len(ctx.history) == 2
        assert ctx.history[0]["role"] == "user"
        assert ctx.history[1]["agent_id"] == "agent1"

    def test_get_recent(self):
        ctx = TaskContext()
        for i in range(20):
            ctx.add_message("user", f"Message {i}")
        recent = ctx.get_recent(5)
        assert len(recent) == 5
        assert recent[0]["content"] == "Message 15"


class TestTask:
    def test_default_status(self):
        t = Task(input_text="test")
        assert t.status == TaskStatus.PENDING
        assert t.task_id  # UUID generated
