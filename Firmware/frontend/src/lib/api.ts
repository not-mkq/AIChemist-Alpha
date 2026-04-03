import axios from 'axios';

const client = axios.create({
  baseURL: '/api',
  timeout: 60000,
});

const fileAgentClient = axios.create({
  // file_agent 独立监听在本地端口，由前端直接访问。
  // 如需调整，可在构建时通过 VITE_FILE_AGENT_URL 注入。
  baseURL: (import.meta as any).env?.VITE_FILE_AGENT_URL ?? 'http://127.0.0.1:5003',
  timeout: 60000,
});

const auditAgentClient = axios.create({
  // audit_agent 独立监听在本地端口，由前端直接访问。
  baseURL: (import.meta as any).env?.VITE_AUDIT_AGENT_URL ?? 'http://127.0.0.1:5011',
  timeout: 60000,
});

export async function createSession(name?: string) {
  const payload = name ? { name } : undefined;
  const { data } = await client.post('/sessions', payload);
  return data;
}

export async function listSessions() {
  const { data } = await client.get('/sessions');
  return data.sessions;
}

export async function getSession(sessionId: string) {
  const { data } = await client.get(`/sessions/${sessionId}`);
  return data;
}

export async function getEvents(sessionId: string) {
  const { data } = await client.get(`/sessions/${sessionId}/events`);
  return data.events;
}

export async function sendMessage(
  sessionId: string,
  content: string,
  opts?: { contextVersion?: number | null; userTag?: string | null }
) {
  const payload: Record<string, unknown> = { content };
  if (opts?.contextVersion != null) payload.context_version = opts.contextVersion;
  if (opts?.userTag) payload.user_tag = opts.userTag;
  const { data } = await client.post(`/sessions/${sessionId}/messages`, payload);
  return data;
}

export async function getTaskStatus(taskId: string) {
  const { data } = await client.get(`/tasks/${taskId}`);
  return data;
}

export async function closeSession(sessionId: string) {
  const { data } = await client.post(`/sessions/${sessionId}/close`);
  return data;
}

export async function resolveAudit(sessionId: string, auditId: string, decision: 'approve' | 'reject', note?: string) {
  const { data } = await client.post(`/sessions/${sessionId}/audit/${auditId}`, {
    decision,
    note,
  });
  return data;
}

export async function fetchLogTail() {
  const { data } = await client.get('/logs/latest');
  return data;
}

export async function listAgents() {
  const { data } = await client.get('/agents');
  return data.agents;
}

export async function listWorkspaceFiles() {
  const { data } = await client.get('/workspace/files');
  return data.files;
}

export async function getWorkspaceIndex() {
  const { data } = await client.get('/workspace/index');
  return data;
}

export async function pollWorkspaceUpdates(since: number) {
  const { data } = await client.get('/workspace/updates', { params: { since } });
  return data;
}

export async function previewWorkspaceFile(path: string) {
  const { data } = await client.get('/workspace/file', { params: { path } });
  return data;
}

export async function uploadWorkspaceFile(file: File, targetPath?: string) {
  const form = new FormData();
  form.append('file', file);
  if (targetPath) form.append('path', targetPath);
  const { data } = await client.post('/workspace/file/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data;
}

export async function uploadSessionFile(sessionId: string, file: File, options?: { targetPath?: string; taskId?: string | null }) {
  const form = new FormData();
  form.append('file', file);
  if (options?.targetPath) form.append('path', options.targetPath);
  if (options?.taskId) form.append('task_id', options.taskId);
  const { data } = await client.post(`/sessions/${sessionId}/file/upload`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data as {
    task_id?: string | null;
    path: string;
    name: string;
    download_url: string;
    overwritten?: boolean;
    user_filename?: string | null;
  };
}

export async function exportSessionPdf(sessionId: string) {
  const { data } = await client.get(`/sessions/${sessionId}/export/pdf`, {
    responseType: 'blob',
  });
  return data as Blob;
}

// --- file_agent 协议：前端直接与 file_agent 互通（step 5、8） ---

export async function listFileAgentTasks(sessionId: string) {
  const { data } = await fileAgentClient.get('/ui/tasks', { params: { session_id: sessionId } });
  return data.tasks as Array<{
    task_id: string;
    session_id: string;
    call_id: string;
    method: string;
    filename?: string | null;
    user_filename?: string | null;
    validation?: Record<string, unknown> | null;
  }>;
}

export async function notifyFileAgentUpload(
  taskId: string,
  payload: { workspacePath: string; userFilename: string; overwritten?: boolean },
) {
  const { data } = await fileAgentClient.post(`/ui/tasks/${taskId}/uploaded`, {
    workspace_path: payload.workspacePath,
    user_filename: payload.userFilename,
    overwritten: payload.overwritten ?? false,
  });
  return data;
}

// 前端根据 file_agent 任务，显式写入 file_upload_prompt 事件（step 6）
export async function createFileUploadPromptEvent(sessionId: string, payload: Record<string, unknown>) {
  const { data } = await client.post(`/sessions/${sessionId}/events/file_upload_prompt`, payload);
  return data;
}

// --- audit_agent 协议：前端直接与 audit_agent 互通（step 5-8） ---

export async function listAuditAgentTasks(sessionId: string) {
  const { data } = await auditAgentClient.get('/ui/tasks', { params: { session_id: sessionId } });
  return data.tasks as Array<{
    task_id: string;
    session_id: string;
    call_id?: string | null;
    tool_name: string;
    arguments: Record<string, unknown>;
    ai_decision?: Record<string, unknown> | null;
    rules?: unknown;
    risk_score?: number | null;
  }>;
}

export async function resolveAuditAgentTask(
  taskId: string,
  payload: { approved: boolean; note?: string; actor?: string }
) {
  const { data } = await auditAgentClient.post(`/ui/tasks/${taskId}/resolved`, payload);
  return data;
}

export async function createAuditRequestEvent(sessionId: string, payload: Record<string, unknown>) {
  const { data } = await client.post(`/sessions/${sessionId}/events/audit_request`, payload);
  return data;
}

export async function createAuditDecisionEvent(sessionId: string, payload: Record<string, unknown>) {
  const { data } = await client.post(`/sessions/${sessionId}/events/audit_decision`, payload);
  return data;
}

export async function exportSessionHtml(sessionId: string) {
  const { data } = await client.get(`/sessions/${sessionId}/export/html`, {
    responseType: 'blob',
  });
  return data as Blob;
}

export async function listHistorySessions() {
  const { data } = await client.get('/history/sessions');
  return data.sessions;
}

export async function getHistorySession(sessionId: string) {
  const { data } = await client.get(`/history/sessions/${sessionId}`);
  return data;
}

export async function deleteHistorySession(sessionId: string) {
  const { data } = await client.delete(`/history/sessions/${sessionId}`);
  return data;
}

export async function loadHistorySession(
  sessionId: string,
  opts?: { version?: number | null; userTag?: string | null; fromEvents?: boolean }
) {
  const payload: Record<string, unknown> = {};
  if (opts?.version != null) payload.version = opts.version;
  if (opts?.userTag) payload.user_tag = opts.userTag;
  if (opts?.fromEvents) payload.from_events = true;
  const { data } = await client.post(`/history/sessions/${sessionId}/load`, payload);
  return data;
}

export async function cloneHistorySession(sessionId: string, name?: string) {
  const payload = name ? { name } : undefined;
  const { data } = await client.post(`/history/sessions/${sessionId}/clone`, payload);
  return data;
}

export async function getContextInfo(
  sessionId: string,
  opts?: { version?: number | null; userTag?: string | null; includeMessages?: boolean }
) {
  const params: Record<string, unknown> = {};
  if (opts?.version != null) params.version = opts.version;
  if (opts?.userTag) params.user_tag = opts.userTag;
  if (opts?.includeMessages) params.include_messages = true;
  const { data } = await client.get(`/sessions/${sessionId}/context`, { params });
  return data;
}

export async function listContextVersions(sessionId: string) {
  const { data } = await client.get(`/history/sessions/${sessionId}/contexts`);
  return data.versions as Array<{ id: number; version: number; user_tag?: string | null; created_at?: string }>;
}

export async function compressContext(
  sessionId: string,
  opts?: { version?: number | null; userTag?: string | null; newTag?: string | null }
) {
  const payload: Record<string, unknown> = {};
  if (opts?.version != null) payload.version = opts.version;
  if (opts?.userTag) payload.user_tag = opts.userTag;
  if (opts?.newTag) payload.new_tag = opts.newTag;
  const { data } = await client.post(`/sessions/${sessionId}/context/compress`, payload);
  return data;
}
