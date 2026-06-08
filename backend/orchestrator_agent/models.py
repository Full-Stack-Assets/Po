"""
Core data models for the orchestration system.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
from datetime import datetime
import uuid


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExecutionMode(Enum):
    SEQUENTIAL = "sequential"
    CONCURRENT = "concurrent"
    HIERARCHICAL = "hierarchical"


class AgentCapability(Enum):
    RESEARCH = "research"
    WRITING = "writing"
    CODE_GENERATION = "code_generation"
    ANALYSIS = "analysis"
    SUMMARIZATION = "summarization"
    PLANNING = "planning"
    TOOL_USE = "tool_use"


@dataclass
class Constraint:
    """A single resource constraint with a budget and current usage."""
    name: str
    max_value: float
    current_value: float = 0.0
    unit: str = ""
    hard_limit: bool = True

    @property
    def remaining(self) -> float:
        return max(0.0, self.max_value - self.current_value)

    @property
    def utilization(self) -> float:
        return self.current_value / self.max_value if self.max_value > 0 else 0.0

    @property
    def is_exceeded(self) -> bool:
        return self.current_value > self.max_value

    def consume(self, amount: float) -> bool:
        if self.hard_limit and self.current_value + amount > self.max_value:
            return False
        self.current_value += amount
        return True

    def reset(self):
        self.current_value = 0.0


@dataclass
class TokenUsage:
    """Token usage and cost accounting for a single completion."""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    input_cost: float = 0.0
    output_cost: float = 0.0
    total_cost: float = 0.0
    currency: str = "USD"


@dataclass
class TaskContext:
    """Shared context passed between agents during orchestration."""
    conversation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    history: List[Dict[str, Any]] = field(default_factory=list)
    shared_state: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_message(self, role: str, content: str, agent_id: str = ""):
        self.history.append({
            "role": role,
            "content": content,
            "agent_id": agent_id,
            "timestamp": datetime.utcnow().isoformat(),
        })

    def get_recent(self, n: int = 10) -> List[Dict[str, Any]]:
        return self.history[-n:]

    def to_messages(self, system_prompt: str,
                    max_history: int = 10) -> list:
        from orchestrator_agent.llm_providers import Message
        msgs = [Message(role="system", content=system_prompt)]
        for entry in self.get_recent(max_history):
            msgs.append(Message(role=entry["role"], content=entry["content"]))
        return msgs


@dataclass
class AgentResult:
    """Result returned by a sub-agent after execution."""
    agent_id: str
    task_id: str
    output: str
    success: bool = True
    error: Optional[str] = None
    tokens_used: int = 0
    cost: float = 0.0
    latency_ms: float = 0.0
    model_used: str = ""
    provider_used: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentProfile:
    """Metadata describing a registered sub-agent's capabilities."""
    agent_id: str
    name: str
    capabilities: List[AgentCapability] = field(default_factory=list)
    supported_intents: List[str] = field(default_factory=list)
    cost_per_1k_tokens: float = 0.0
    avg_latency_ms: float = 0.0
    priority: int = 0
    max_concurrent: int = 5
    active_tasks: int = 0
    enabled: bool = True
    preferred_capability: str = "research"
    preferred_provider: Optional[str] = None
    preferred_model: Optional[str] = None


@dataclass
class Task:
    """A unit of work to be executed by a sub-agent."""
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    intent: str = ""
    input_text: str = ""
    assigned_agent: str = ""
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[AgentResult] = None
    priority: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    parent_task_id: Optional[str] = None
    subtasks: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
