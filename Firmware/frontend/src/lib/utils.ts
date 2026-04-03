import { marked } from 'marked';
import type { AuditDecisionInfo, TimelineEvent, WorkspaceFile } from './types';
import { ROLE_META } from './constants';

export function formatTime(ts: string) {
  return new Date(ts).toLocaleTimeString('zh-CN', {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

const htmlEscapeMap: Record<string, string> = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
};

export function escapeHtml(str: string) {
  return str.replace(/[&<>"']/g, (char) => htmlEscapeMap[char] ?? char);
}

function decodeHtmlEntities(str: string) {
  return str.replace(/&(?:amp;)?#(\d+);/g, (_, code) => {
    const num = Number(code);
    if (Number.isNaN(num)) return _;
    return String.fromCharCode(num);
  });
}

export function highlightJson(obj?: unknown) {
  if (obj === undefined) return '';
  const json = escapeHtml(JSON.stringify(obj, null, 2));
  const highlighted = json.replace(
    /("(\\u[\da-fA-F]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g,
    (match) => {
      let cls = 'json-number';
      if (/^"/.test(match)) {
        cls = /:$/.test(match) ? 'json-key' : 'json-string';
      } else if (/true|false/.test(match)) {
        cls = 'json-boolean';
      } else if (/null/.test(match)) {
        cls = 'json-null';
      }
      const rendered = cls === 'json-string' ? match.replace(/&#39;/g, "'") : match;
      return `<span class="${cls}">${rendered}</span>`;
    }
  );
  return decodeHtmlEntities(highlighted);
}

export function renderMarkdown(text?: string) {
  if (!text) return '';
  const normalized = text.replace(/\\n/g, '\n');
  return marked.parse(normalized, { breaks: true });
}

export function riskClass(score?: number) {
  if (score === undefined || score === null) return '';
  if (score >= 70) return 'risk-high';
  if (score >= 40) return 'risk-mid';
  return 'risk-low';
}

const asRecord = (value: unknown): Record<string, unknown> | undefined => {
  if (!value || typeof value !== 'object') return undefined;
  return value as Record<string, unknown>;
};

const asString = (value: unknown): string | undefined => {
  if (typeof value !== 'string') return undefined;
  const trimmed = value.trim();
  return trimmed ? trimmed : undefined;
};

export function resolvedEventType(evt: TimelineEvent) {
  if (evt.type === 'audit' && evt.payload && typeof evt.payload.type === 'string') {
    return evt.payload.type as string;
  }
  return evt.raw_type || evt.type;
}

export function toolResultPayload(evt: TimelineEvent) {
  const payload = asRecord(evt.payload);
  if (payload) {
    const direct = asRecord(payload.result);
    if (direct) return direct;
    const detail = asRecord(payload.detail);
    const detailResult = detail ? asRecord(detail.result) : undefined;
    if (detailResult) return detailResult;
  }
  return asRecord(evt.result);
}

export function auditIdOfEvent(evt: TimelineEvent): string | undefined {
  const direct = asString(evt.audit_id);
  if (direct) return direct;
  const payload = asRecord(evt.payload);
  if (payload) {
    const payloadAudit = asString(payload.audit_id) ?? asString(payload.audit_ticket_id);
    if (payloadAudit) return payloadAudit;
  }
  const flagsAudit = asString(asRecord(evt.flags)?.audit_id);
  if (flagsAudit) return flagsAudit;
  const result = toolResultPayload(evt);
  if (result) {
    const resultAudit =
      asString(result.audit_ticket_id) ??
      asString(result.audit_id) ??
      asString(asRecord(result.detail)?.audit_ticket_id);
    if (resultAudit) return resultAudit;
  }
  return undefined;
}

export function eventMeta(evt: TimelineEvent, lang: 'zh' | 'en' = 'zh') {
  const resolvedType = resolvedEventType(evt);
  const meta = ROLE_META[resolvedType] ?? ROLE_META.system;
  const payload = evt.payload ?? {};
  const subtitle = (payload.tool as string) || (payload.tool_name as string) || undefined;
  const resolvedContent =
    typeof evt.content === 'string'
      ? evt.content
      : typeof payload.content === 'string'
        ? (payload.content as string)
        : '';
  let body = '';
  if (evt.type === 'user_message' || evt.type === 'assistant_message') body = resolvedContent;
  if (resolvedType === 'audit_request') {
    const summary = (payload.ai_decision as AuditDecisionInfo | undefined)?.summary;
    body = summary ?? '';
  }
  if (resolvedType === 'audit_decision') {
    const approved = payload.approved;
    body =
      typeof approved === 'boolean'
        ? approved
          ? (lang === 'zh' ? '已通过' : 'Approved')
          : (lang === 'zh' ? '已拒绝' : 'Rejected')
        : '';
  }

  return {
    ...meta,
    label: lang === 'zh' ? meta.label : meta.label_en,
    hint: lang === 'zh' ? meta.hint : meta.hint_en,
    subtitle,
    body
  };
}

function escapeRegExp(str: string) {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

export function linkFilesInText(text: string | undefined, files: WorkspaceFile[]) {
  if (!text || !files.length) return text;

  const entries = [...files].sort((a, b) => b.path.length - a.path.length);

  const replaceOutsideCode = (segment: string) => {
    let updated = segment;
    for (const file of entries) {
      const encoded = encodeURIComponent(file.path);
      const replacement = `[${file.path}](workspace://${encoded})`;
      updated = updated.replace(new RegExp(`${escapeRegExp(file.path)}`, 'g'), replacement);
      if (file.name && file.name !== file.path) {
        const nameReplacement = `[${file.name}](workspace://${encoded})`;
        updated = updated.replace(new RegExp(`${escapeRegExp(file.name)}`, 'g'), nameReplacement);
      }
    }
    return updated;
  };

  // Skip replacements inside fenced code blocks (``` ``` ) and inline code (` `).
  // Process fenced blocks first.
  const fencedRegex = /```[\s\S]*?```/g;
  let result = '';
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = fencedRegex.exec(text)) !== null) {
    const before = text.slice(lastIndex, match.index);
    const codeBlock = match[0];
    // Within non-code, also skip inline code marked by backticks.
    const inlinePatched = before.split(/(`[^`]*`)/g).map((chunk) => {
      if (chunk.startsWith('`') && chunk.endsWith('`')) return chunk;
      return replaceOutsideCode(chunk);
    });
    result += inlinePatched.join('');
    result += codeBlock;
    lastIndex = match.index + codeBlock.length;
  }
  // Tail after the last fenced block.
  const tail = text.slice(lastIndex);
  const tailPatched = tail.split(/(`[^`]*`)/g).map((chunk) => {
    if (chunk.startsWith('`') && chunk.endsWith('`')) return chunk;
    return replaceOutsideCode(chunk);
  });
  result += tailPatched.join('');

  return result;
}
