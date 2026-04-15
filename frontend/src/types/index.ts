export interface User {
  user_id: number;
  email: string | null;
  display_name: string | null;
  telegram_username: string | null;
  is_allowed: boolean;
}

export interface Session {
  session_id: string;
  project_path: string;
  last_used: string;
  total_turns: number;
  total_cost: number;
  created_at?: string;
  message_count?: number;
  is_active?: boolean;
  /** How many times SDK compaction has occurred in this session. */
  compact_count?: number;
  /** Input tokens of the last message = current context window usage. */
  context_tokens?: number;
  /** Max context tokens for this session (from SDK). */
  context_max_tokens?: number;
  /** Channel that last used this session ("telegram" | "web"). */
  last_channel?: string;
  /** Channel currently running this session (only set when active). */
  running_channel?: string;
  /** Human-readable session name (e.g. "swift-badger"). */
  display_name?: string;
}

export interface ChatRequest {
  message: string;
  session_id?: string | null;
  mode?: "yolo" | "plan" | "approve";
  cwd?: string | null;
  stream?: boolean;
}

export interface ChatResponse {
  content: string;
  session_id: string | null;
  cost: number;
  duration_ms: number;
  tools_used: string[];
}

export type ChatEvent =
  | { event: "tool_start"; tool: string; input: Record<string, unknown> }
  | { event: "tool_result"; tool: string; success: boolean; duration: number; preview: string }
  | { event: "text"; content: string }
  | { event: "done"; session_id: string; cost: number; duration_ms: number }
  | { event: "error"; message: string }
  | { event: "context_usage"; input_tokens: number; max_tokens: number; percentage?: number };

export interface BotStatus {
  instance_name: string;
  uptime_seconds: number;
  claude_cli: string;
  active_sessions: number;
  total_messages: number;
  total_cost: number;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  tools?: ToolEvent[];
  thinking?: string;       // latest reasoning/thinking text snippet
  timestamp: Date;
  commandTitle?: string;   // for system messages from slash commands
}

export interface ToolEvent {
  tool: string;
  input?: Record<string, unknown>;
  success?: boolean;
  duration?: number;
  preview?: string;
  status: "running" | "done" | "error";
  isBackgroundTask?: boolean;
}

// ── User Profile & Preferences ────────────────────────────────────────────
export interface UserPreferences {
  permission_mode: "yolo" | "approve" | "plan";
  model: "default" | "sonnet" | "opus" | "haiku";
  thinking: boolean;
  max_turns: number;
  budget: number | null; // USD per message, null = unbegrenzt
  verbose: 0 | 1 | 2;
  working_directory: string;
  display_name?: string;
  language?: string;
  github_username?: string;
  github_org?: string;
  email?: string;
  custom_instructions?: string;
}

export interface UserProfile {
  user_id: number;
  email: string | null;
  display_name: string | null;
  telegram_username: string | null;
  total_cost: number;
  message_count: number;
  session_count: number;
  preferences: UserPreferences;
}

// ── Statistics ────────────────────────────────────────────────────────────
export interface ModelStat {
  model: string;
  messages: number;
  cost: number;
  input_tokens: number;
  output_tokens: number;
  cache_creation_tokens: number;
  cache_read_tokens: number;
}

export interface UserStats {
  total_messages: number;
  total_sessions: number;
  total_cost: number;
  input_tokens: number;
  output_tokens: number;
  cache_creation_tokens: number;
  cache_read_tokens: number;
  by_model: ModelStat[];
}

// ── Daily Stats ───────────────────────────────────────────────────────────
export interface DailyStatRow {
  date: string;          // "2026-03-15"
  model: string;
  input_tokens: number;
  output_tokens: number;
  cache_creation_tokens: number;
  cache_read_tokens: number;
  cost: number;
  messages: number;
}

export interface ToolStat {
  tool_name: string;
  count: number;
}

// ── Cluster ───────────────────────────────────────────────────────────────
export interface ClusterPod {
  name: string;
  namespace: string;
  phase: string;
  ready: boolean;
  restarts: number;
  cpu_req_m: number;
  mem_req_mib: number;
  cpu_usage_m?: number | null;
  mem_usage_mib?: number | null;
  node: string;
}

export interface ClusterNamespace {
  namespace: string;
  total: number;
  running: number;
  pods: ClusterPod[];
}

export interface ClusterNode {
  name: string;
  ready: boolean;
  arch: string;
  role: string;
  cpu_capacity: number;
  mem_capacity_mib: number;
  cpu_allocatable: number;
  mem_allocatable_mib: number;
  cpu_usage_m?: number | null;
  mem_usage_mib?: number | null;
  pod_count: number;
}

export interface ClusterStatus {
  namespaces: ClusterNamespace[];
  nodes: ClusterNode[];
  top_pods: ClusterPod[];
  total_pods: number;
  running_pods: number;
  total_nodes: number;
  ready_nodes: number;
  has_metrics: boolean;
}

export interface CronJobInfo {
  name: string;
  schedule: string;
  description: string;
  last_run: string | null;
  last_successful: string | null;
  active: number;
  created_at: string;
}

export interface JobInfo {
  name: string;
  description: string;
  start_time: string | null;
  completion_time: string | null;
  succeeded: number;
  failed: number;
  active: number;
  status: "succeeded" | "failed" | "running";
  created_at: string;
}

export interface JobsStatus {
  cronjobs: CronJobInfo[];
  jobs: JobInfo[];
}

// ── Slash Commands ──────────────────────────────────────────────────────
export interface SubcommandDef {
  name: string;
  description: string;
  args_placeholder?: string | null;
}

export interface CommandDef {
  name: string;
  icon: string;
  description: string;
  is_dispatcher: boolean;
  subcommands: SubcommandDef[];
}

export interface CommandResponse {
  success: boolean;
  title: string;
  content: string;
  data?: Record<string, unknown>;
  error?: string;
}
