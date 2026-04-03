import { writable } from 'svelte/store';
import type {
  SessionSummary,
  TimelineEvent,
  WorkspaceFile,
  WorkspacePreview,
  UiState,
  AgentDoc,
} from './types';

export const sessionsStore = writable<SessionSummary[]>([]);
export const activeSessionStore = writable<string | null>(null);
export const contextVersionStore = writable<number | null>(null);
export const contextTagStore = writable<string | null>(null);
export const eventsStore = writable<TimelineEvent[]>([]);
export const auditNotesStore = writable<Record<string, string>>({});
export const agentDocsStore = writable<Record<string, AgentDoc>>({});
export const workspaceFilesStore = writable<WorkspaceFile[]>([]);
export const filePreviewStore = writable<WorkspacePreview | null>(null);
export const uiStateStore = writable<UiState>({
  showLog: false,
  showFileManager: false,
  showFilePreview: false,
  exportingPdf: false,
  exportingHtml: false,
  showHistory: false,
});
