"""
Constraint-Optimized LLM Agent Orchestration System
====================================================
Multi-provider agent orchestration framework with intelligent routing,
constraint management, fallback chains, and streaming support.

Providers: OpenAI, Anthropic, Azure OpenAI, Google Gemini, Mistral, Ollama, OpenRouter
"""

__version__ = "3.0.0"
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
from orchestrator_agent.tools import (
    Tool, ToolResult, ToolRegistry, EmailOutboundTool,
    ContentGeneratorTool, WebResearchTool, DeployHealthCheckTool,
    LandingPageTool, default_tool_registry,
)
from orchestrator_agent.scheduler import (
    WorkflowScheduler, ScheduleEntry, DigestReport,
)
from orchestrator_agent.auth import (
    AuthManager, InMemoryUserStore, User, UserStore, Session,
)
from orchestrator_agent.conversations import (
    InMemoryConversationStore, ConversationStore,
    Conversation, ChatMessage, MessageRole,
)
from orchestrator_agent.analytics import (
    AnalyticsEngine, DashboardMetrics, TimeSeriesPoint,
    CostBreakdown, ProviderMetrics,
)
from orchestrator_agent.config_api import (
    ConfigManager, SystemConfig, ProviderSetting,
    ConstraintSetting, TrustSettings,
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
    # Tools
    "Tool", "ToolResult", "ToolRegistry", "EmailOutboundTool",
    "ContentGeneratorTool", "WebResearchTool", "DeployHealthCheckTool",
    "LandingPageTool", "default_tool_registry",
    # Scheduler
    "WorkflowScheduler", "ScheduleEntry", "DigestReport",
    # Auth
    "AuthManager", "InMemoryUserStore", "User", "UserStore", "Session",
    # Conversations
    "InMemoryConversationStore", "ConversationStore",
    "Conversation", "ChatMessage", "MessageRole",
    # Analytics
    "AnalyticsEngine", "DashboardMetrics", "TimeSeriesPoint",
    "CostBreakdown", "ProviderMetrics",
    # Config
    "ConfigManager", "SystemConfig", "ProviderSetting",
    "ConstraintSetting", "TrustSettings",
]
