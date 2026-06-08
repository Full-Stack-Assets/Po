"""
Constraint-Optimized LLM Agent Orchestration System
====================================================
Multi-provider agent orchestration framework with intelligent routing,
constraint management, fallback chains, and streaming support.

Providers: OpenAI, Anthropic, Azure OpenAI, Google Gemini, Mistral, Ollama
"""

__version__ = "2.0.0"
__author__ = "Nicholas Albertson"

from orchestrator_agent.models import (
    Task, TaskContext, TaskStatus, AgentResult, AgentProfile,
    AgentCapability, Constraint, ExecutionMode,
)
from orchestrator_agent.llm_providers import (
    ProviderType, ProviderConfig, Message, LLMResponse, LLMChunk,
    TokenUsage, ModelInfo, BaseLLMProvider, create_provider,
)
from orchestrator_agent.llm_manager import LLMManager, FallbackChain, ModelSelector
from orchestrator_agent.agents import (
    SubAgent, ResearchAgent, WriterAgent, CodeAgent,
    AnalysisAgent, SummarizerAgent, PlannerAgent,
)
from orchestrator_agent.orchestrator import OrchestratorAgent
from orchestrator_agent.validation import (
    ValidationGate, ValidationResult, ValidationScore,
)
from orchestrator_agent.verification import VerificationLayer, VerificationResult
from orchestrator_agent.verifiers import (
    Verifier, HttpDeployVerifier, EmailDeliverabilityVerifier,
    StripeWebhookVerifier, default_verifiers,
)
from orchestrator_agent.signals import (
    SignalScorer, SubScore, GoogleSuggestDemandScorer,
    SuggestCompetitorScorer, RedditWTPScorer, HeuristicICPScorer,
    default_live_scorers,
)
from orchestrator_agent.approvals import (
    ApprovalManager, ApprovalPolicy, ApprovalRequest,
    ApprovalDecision, ApprovalType,
)
from orchestrator_agent.persistence import (
    TrustStore, InMemoryTrustStore, PostgresTrustStore, create_trust_store,
)
from orchestrator_agent.checkpoint import (
    WorkflowRunner, WorkflowState, Checkpointer,
)

__all__ = [
    "OrchestratorAgent", "LLMManager", "FallbackChain", "ModelSelector",
    "SubAgent", "ResearchAgent", "WriterAgent", "CodeAgent",
    "AnalysisAgent", "SummarizerAgent", "PlannerAgent",
    "Task", "TaskContext", "TaskStatus", "AgentResult", "AgentProfile",
    "AgentCapability", "Constraint", "ExecutionMode",
    "ProviderType", "ProviderConfig", "Message", "LLMResponse",
    "LLMChunk", "TokenUsage", "ModelInfo", "BaseLLMProvider",
    "create_provider",
    # Po trust layer
    "ValidationGate", "ValidationResult", "ValidationScore",
    "VerificationLayer", "VerificationResult",
    "Verifier", "HttpDeployVerifier", "EmailDeliverabilityVerifier",
    "StripeWebhookVerifier", "default_verifiers",
    "SignalScorer", "SubScore", "GoogleSuggestDemandScorer",
    "SuggestCompetitorScorer", "RedditWTPScorer", "HeuristicICPScorer",
    "default_live_scorers",
    "ApprovalManager", "ApprovalPolicy", "ApprovalRequest",
    "ApprovalDecision", "ApprovalType",
    "TrustStore", "InMemoryTrustStore", "PostgresTrustStore",
    "create_trust_store",
    "WorkflowRunner", "WorkflowState", "Checkpointer",
]
