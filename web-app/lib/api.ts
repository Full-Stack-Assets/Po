const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "";
const API_KEY = process.env.NEXT_PUBLIC_API_KEY;

// ---------- Request types ----------

export interface OrchestrateRequest {
  input: string;
  conversation_id?: string;
  mode?: "sequential" | "concurrent";
  stream?: boolean;
  validate?: boolean;
  validation_override?: boolean;
}

export interface BatchRequest {
  inputs: string[];
  conversation_id?: string;
  mode?: string;
}

export interface ApprovalDecision {
  approved: boolean;
  edited_input?: string;
  conversation_id?: string;
}

export interface WorkflowPlanRequest {
  goal: string;
  conversation_id?: string;
  thread_id?: string;
}

export interface WorkflowRunRequest {
  steps: any[];
  conversation_id?: string;
  thread_id?: string;
  default_intent?: string;
}

export interface WorkflowResumeRequest {
  conversation_id?: string;
}

export interface ToolExecuteRequest {
  tool: string;
  params: Record<string, any>;
}

export interface ScheduleCreateRequest {
  name: string;
  goal: string;
  interval_seconds: number;
  max_runs?: number;
}

// ---------- Response types ----------

export interface ValidationResult {
  overall_score: number;
  score: "red" | "yellow" | "green";
}

export interface VerificationResult {
  passed: number;
  failed: number;
  all_passed: boolean;
}

export interface ApprovalInfo {
  id: string;
  type: string;
  summary: string;
}

export interface OrchestrationResult {
  success: boolean;
  intent: string;
  model_used: string;
  provider_used: string;
  output: string;
  cost_usd: number;
  tokens_used: number;
  latency_ms: number;
  validation?: ValidationResult;
  verification?: VerificationResult;
  approval?: ApprovalInfo;
  error?: string;
  refunded?: boolean;
}

export interface BatchResponse {
  results: OrchestrationResult[];
}

export interface Approval {
  approval_id: string;
  type: string;
  summary: string;
  created_at: string;
  status: string;
  payload: any;
}

export interface ApprovalsResponse {
  approvals: Approval[];
}

export interface WorkflowPlanResponse {
  status: string;
  plan_raw?: string;
  results: OrchestrationResult[];
  error?: string;
}

export interface WorkflowResult {
  [key: string]: any;
}

export interface WorkflowState {
  [key: string]: any;
}

export interface RunEntry {
  intent: string;
  success: boolean;
  cost_usd: number;
  output: string;
  created_at: string;
}

export interface RunsResponse {
  runs: RunEntry[];
}

export interface StatsResponse {
  total_runs: number;
  success_rate: number;
  verified_runs: number;
  refunded_runs: number;
  persistence: string;
}

export interface ProviderStatus {
  provider: string;
  circuit_open: boolean;
}

export interface AgentInfo {
  name: string;
}

export interface Constraint {
  name: string;
  used: number;
  max: number;
  unit: string;
}

export interface StatusResponse {
  providers: ProviderStatus[];
  agents: AgentInfo[];
  constraints: Constraint[];
}

export interface HealthResponse {
  status: string;
  providers: any;
  usage: any;
}

export interface ToolInfo {
  name: string;
  description: string;
}

export interface ToolsResponse {
  tools: ToolInfo[];
}

export interface ToolResult {
  [key: string]: any;
}

export interface SchedulesResponse {
  schedules: any[];
}

export interface ApiError {
  error: string;
  status: number;
}

// ---------- Client ----------

type ApiResult<T> = T | ApiError;

function isApiError(value: unknown): value is ApiError {
  return (
    typeof value === "object" &&
    value !== null &&
    "error" in value &&
    "status" in value
  );
}

class ApiClient {
  private baseUrl: string;
  private apiKey?: string;

  constructor(baseUrl: string, apiKey?: string) {
    this.baseUrl = baseUrl;
    this.apiKey = apiKey;
  }

  private headers(): HeadersInit {
    const h: Record<string, string> = {
      "Content-Type": "application/json",
    };
    if (this.apiKey) {
      h["Authorization"] = `Bearer ${this.apiKey}`;
    }
    return h;
  }

  private async request<T>(
    method: string,
    path: string,
    body?: unknown,
  ): Promise<ApiResult<T>> {
    try {
      const res = await fetch(`${this.baseUrl}${path}`, {
        method,
        headers: this.headers(),
        body: body !== undefined ? JSON.stringify(body) : undefined,
      });
      const data = await res.json();
      if (!res.ok) {
        return {
          error: data?.detail ?? data?.error ?? res.statusText,
          status: res.status,
        } as ApiError;
      }
      return data as T;
    } catch (err) {
      return {
        error: err instanceof Error ? err.message : "Unknown error",
        status: 0,
      } as ApiError;
    }
  }

  private get<T>(path: string) {
    return this.request<T>("GET", path);
  }

  private post<T>(path: string, body?: unknown) {
    return this.request<T>("POST", path, body);
  }

  private del<T>(path: string) {
    return this.request<T>("DELETE", path);
  }

  // Orchestration
  orchestrate(body: OrchestrateRequest) {
    return this.post<OrchestrationResult>("/v2/orchestrate", body);
  }

  batch(body: BatchRequest) {
    return this.post<BatchResponse>("/v2/batch", body);
  }

  // Approvals
  getApprovals() {
    return this.get<ApprovalsResponse>("/v2/approvals");
  }

  resolveApproval(id: string, body: ApprovalDecision) {
    return this.post<OrchestrationResult>(`/v2/approvals/${id}`, body);
  }

  // Workflows
  planWorkflow(body: WorkflowPlanRequest) {
    return this.post<WorkflowPlanResponse>("/v2/workflows/plan", body);
  }

  runWorkflow(body: WorkflowRunRequest) {
    return this.post<WorkflowResult>("/v2/workflows", body);
  }

  resumeWorkflow(threadId: string, body: WorkflowResumeRequest = {}) {
    return this.post<WorkflowResult>(
      `/v2/workflows/${threadId}/resume`,
      body,
    );
  }

  getWorkflow(threadId: string) {
    return this.get<WorkflowState>(`/v2/workflows/${threadId}`);
  }

  // Runs & Stats
  getRuns(limit?: number) {
    const q = limit !== undefined ? `?limit=${limit}` : "";
    return this.get<RunsResponse>(`/v2/runs${q}`);
  }

  getStats() {
    return this.get<StatsResponse>("/v2/stats");
  }

  // System
  getStatus() {
    return this.get<StatusResponse>("/v2/status");
  }

  getHealth() {
    return this.get<HealthResponse>("/v2/health");
  }

  getModels() {
    return this.get<any[]>("/v2/models");
  }

  // Tools
  getTools() {
    return this.get<ToolsResponse>("/v2/tools");
  }

  executeTool(body: ToolExecuteRequest) {
    return this.post<ToolResult>("/v2/tools/execute", body);
  }

  // Schedules
  getSchedules() {
    return this.get<SchedulesResponse>("/v2/schedules");
  }

  createSchedule(body: ScheduleCreateRequest) {
    return this.post<any>("/v2/schedules", body);
  }

  runSchedule(id: string) {
    return this.post<any>(`/v2/schedules/${id}/run`);
  }

  pauseSchedule(id: string) {
    return this.post<any>(`/v2/schedules/${id}/pause`);
  }

  resumeSchedule(id: string) {
    return this.post<any>(`/v2/schedules/${id}/resume`);
  }

  deleteSchedule(id: string) {
    return this.del<any>(`/v2/schedules/${id}`);
  }

  // Digest
  getDigest(periodHours?: number) {
    const q = periodHours !== undefined ? `?period_hours=${periodHours}` : "";
    return this.get<any>(`/v2/digest${q}`);
  }
}

export { isApiError, ApiClient };
export type { ApiResult };
export const api = new ApiClient(BASE_URL, API_KEY);
