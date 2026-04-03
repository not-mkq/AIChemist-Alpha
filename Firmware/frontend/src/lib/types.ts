export type AuditAnalysis = {
  analysis?: string;
  possible_causes?: string[];
  recommendations?: string[];
  risk_score?: number;
};

export type AuditDecisionInfo = {
  summary?: string;
  doubts?: string[];
  risk_score?: number;
};

export type EventPayload = {
  content?: string;
  tool?: string;
  tool_name?: string;
  arguments?: Record<string, unknown>;
  result?: Record<string, unknown>;
  audit_id?: string;
  ai_decision?: AuditDecisionInfo;
  approved?: boolean;
  actor?: string;
  note?: string;
  analysis?: AuditAnalysis;
  risk_score?: number;
  [key: string]: unknown;
};

export type TimelineEvent = {
  id?: number;
  session_id?: string;
  index?: number;
  type: string;
  raw_type?: string;
  actor?: string;
  timestamp: string;
  content?: string | null;
  payload?: EventPayload | null;
  flags?: Record<string, unknown> | null;
  tool?: string;
  tool_name?: string;
  arguments?: Record<string, unknown>;
  result?: Record<string, unknown>;
  audit_id?: string;
  ai_decision?: AuditDecisionInfo;
  approved?: boolean;
  note?: string;
  analysis?: AuditAnalysis;
  risk_score?: number;
};

export type AuditBundle = {
  id: string;
  request?: TimelineEvent;
  decision?: TimelineEvent;
  toolResult?: TimelineEvent;
  createdAt: number;
  updatedAt: number;
  status: 'pending' | 'resolved';
};

export type AgentCard = {
  id: string;
  label: string;
  label_en?: string;
  desc: string;
  desc_en?: string;
  icon: string;
  color: string;
};

export type AgentDoc = {
  intro?: string;
  examples?: unknown;
  interface?: unknown;
  info?: unknown;
};

export type SessionSummary = {
  session_id: string;
  label: string;
  name?: string;
  events?: number;
  context_version?: number | null;
  context_user_tag?: string | null;
  pending_audits?: Array<{ audit_id?: string }>;
  status?: string;
};

export type WorkspaceFile = {
  path: string;
  name: string;
  size: number;
  modified: number;
  type: string;
};

export type WorkspacePreview = {
  path: string;
  name: string;
  size: number;
  type: string;
  content?: string | null;
  content_base64?: string;
  download_url: string;
};

export type FileValidationRules = {
  allowed_extensions?: string[];
  csv_headers?: string[];
  csv_min_rows?: number;
  csv_max_rows?: number;
  csv_min_cols?: number;
  csv_max_cols?: number;
  [key: string]: unknown;
};

export type FileTask = {
  task_id: string;
  method: string;
  filename?: string | null;
  user_filename?: string | null;
  validation?: FileValidationRules | Record<string, unknown> | null;
  status: 'pending' | 'in_progress' | 'done' | 'error';
  created_at?: number;
  updated_at?: number;
  raw_input?: Record<string, unknown>;
  [key: string]: unknown;
};

export type UiState = {
  showLog: boolean;
  showFileManager: boolean;
  showFilePreview: boolean;
  exportingPdf: boolean;
  exportingHtml: boolean;
  showHistory: boolean;
  contextLoading?: boolean;
};

export type StatusSummary = {
  events: number;
  pending: number;
};

export type HistorySessionSummary = {
  session_id: string;
  events: number;
  first_event?: string;
  last_event?: string;
  label?: string;
  context_version?: number | null;
  context_user_tag?: string | null;
};

export type AuditCard = {
  id: string;
  tool_name: string;
  summary?: string;
  doubts?: string[];
  risk_score?: number;
  analysis?: AuditAnalysis;
  approved?: boolean;
  note?: string;
  requestTimestamp?: string;
  decisionTimestamp?: string;
};
