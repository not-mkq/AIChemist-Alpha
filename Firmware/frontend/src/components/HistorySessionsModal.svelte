<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import type { HistorySessionSummary } from '../lib/types';
  import { highlightJson, renderMarkdown } from '../lib/utils';
  import { t, language } from '../lib/i18n';

  export let sessions: HistorySessionSummary[] = [];
  export let loading = false;
  export let selectedId: string | null = null;
  export let previewEvents: any[] = [];
  export let deletingId: string | null = null;
  export let loadVersionInput = '';
  export let loadTagInput = '';
  export let forceRebuild = false;
  export let contexts: Array<{ id: number; version: number; user_tag?: string | null; created_at?: string }> = [];
  export let contextsLoading = false;
  export let currentSessionId: string | null = null;
  export let currentContextVersion: number | null = null;
  export let currentContextTag: string | null = null;
  export let contextPreviewMessages: Array<Record<string, any>> = [];
  export let contextPreviewMeta:
    | { version?: number | null; user_tag?: string | null; created_at?: string; meta?: Record<string, unknown> | null }
    | null = null;
  export let contextPreviewVersion: number | null = null;
  export let contextPreviewTag: string | null = null;
  export let contextPreviewSessionId: string | null = null;

  // Externally-bound props used by parent; mark as touched to avoid Svelte unused-export warnings.
  const _externalBindings = [
    previewEvents,
    loadVersionInput,
    loadTagInput,
    forceRebuild,
    currentContextTag,
  ];
  void _externalBindings;

  const dispatch = createEventDispatcher<{
    close: void;
    refresh: void;
    preview: string;
    contextPreview: { sessionId: string; version?: number; userTag?: string };
    delete: string;
    load: { id: string; versionInput: string; tagInput: string; fromEvents: boolean };
    clone: string;
    compress: { sessionId: string; version?: number; userTag?: string };
  }>();

  const formatTs = (ts?: string) => {
    if (!ts) return '-';
    return new Date(ts).toLocaleString($language === 'zh' ? 'zh-CN' : 'en-US', {
      hour12: false,
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const roleMetaFor = (role?: string | null) => {
    const isZh = $language === 'zh';
    const map: Record<string, { label: string; color: string }> = {
      system: { label: isZh ? '系统' : 'SYSTEM', color: '#f472b6' },
      user: { label: isZh ? '用户' : 'USER', color: '#4c6ef5' },
      assistant: { label: isZh ? '助手' : 'AI', color: '#a855f7' },
      tool: { label: isZh ? '工具' : 'TOOL', color: '#10b981' },
    };
    return map[role ?? ''] ?? { label: role?.toUpperCase() ?? (isZh ? '其他' : 'OTHER'), color: '#94a3b8' };
  };

  const textFromContent = (content: unknown) => {
    if (typeof content === 'string') return content;
    if (Array.isArray(content)) {
      const parts = content
        .map((part) => {
          if (typeof part === 'string') return part;
          if (part && typeof part === 'object') {
            const maybeText = (part as any).text ?? (part as any).content;
            return typeof maybeText === 'string' ? maybeText : '';
          }
          return '';
        })
        .filter(Boolean);
      return parts.join('\n');
    }
    if (content && typeof content === 'object') {
      const maybeText = (content as any).text ?? (content as any).content;
      return typeof maybeText === 'string' ? maybeText : '';
    }
    return '';
  };

  const structuredContent = (content: unknown) => {
    if (content === null || content === undefined) return null;
    if (Array.isArray(content)) {
      const textish = textFromContent(content);
      return textish ? null : content;
    }
    if (typeof content === 'object') return content as Record<string, unknown>;
    if (typeof content === 'string') {
      const trimmed = content.trim();
      if (!trimmed) return null;
      if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
        try {
          const parsed = JSON.parse(trimmed);
          if (parsed && typeof parsed === 'object') return parsed;
        } catch {
          /* ignore */
        }
      }
    }
    return null;
  };

  const toolCallsFrom = (msg: Record<string, any>) => {
    const calls = Array.isArray(msg?.tool_calls) ? msg.tool_calls : [];
    return calls.map((tc) => {
      const fn = tc?.function ?? {};
      const argsRaw = fn.arguments ?? tc.arguments;
      let parsedArgs: Record<string, unknown> | null = null;
      if (typeof argsRaw === 'string') {
        try {
          parsedArgs = JSON.parse(argsRaw);
        } catch {
          parsedArgs = null;
        }
      } else if (argsRaw && typeof argsRaw === 'object') {
        parsedArgs = argsRaw as Record<string, unknown>;
      }
      return {
        id: tc.id,
        name: fn.name ?? tc.name ?? ($language === 'zh' ? '调用' : 'Call'),
        parsedArgs,
        rawArgs: argsRaw,
      };
    });
  };

  $: previewMetaChips = (() => {
    const chips: string[] = [];
    const meta = contextPreviewMeta?.meta as Record<string, unknown> | undefined | null;
    if (!meta) return chips;
    const isZh = $language === 'zh';
    if (meta.source) chips.push((isZh ? '来源: ' : 'Source: ') + String(meta.source));
    if (meta.from_version !== undefined && meta.from_version !== null) chips.push((isZh ? '源版本 v' : 'From v') + meta.from_version);
    if (meta.compressed) chips.push(isZh ? '压缩生成' : 'Compressed');
    if (meta.rebuilt) chips.push(isZh ? '事件重建' : 'Rebuilt');
    if (typeof meta.size === 'number') chips.push((isZh ? '消息数 ' : 'Messages ') + meta.size);
    return chips;
  })();

  const formatVersionLabel = (v: { version: number; user_tag?: string | null; created_at?: string }) => {
    const parts = [`v${v.version}`];
    if (v.user_tag) parts.push(v.user_tag);
    if (v.created_at) parts.push(new Date(v.created_at).toLocaleString($language === 'zh' ? 'zh-CN' : 'en-US'));
    return parts.join(' · ');
  };

  const matchesPreviewContext = (version: number, userTag?: string | null) => {
    if (contextPreviewVersion === null) return false;
    if (contextPreviewSessionId && selectedId !== contextPreviewSessionId) return false;
    const normalizedTag = userTag ?? null;
    const normalizedPreviewTag = contextPreviewTag ?? null;
    return version === contextPreviewVersion && normalizedTag === normalizedPreviewTag;
  };

  $: previewContextLabel = (() => {
    if (!selectedId || contextPreviewVersion === null) return null;
    const target = contexts.find(
      (ctx) =>
        ctx.version === contextPreviewVersion &&
        (ctx.user_tag ?? null) === (contextPreviewTag ?? null)
    );
    if (target) return formatVersionLabel(target);
    return `v${contextPreviewVersion}${contextPreviewTag ? ` · ${contextPreviewTag}` : ''}`;
  })();
</script>

<div class="modal-backdrop topmost" role="presentation" tabindex="-1" on:click={(event) => {
    if (event.target === event.currentTarget) dispatch('close');
  }}>
  <div class="modal wide" role="dialog" aria-modal="true">
    <header class="modal-header">
      <h3>{$t('history.title')}</h3>
      <button class="ghost" on:click={() => dispatch('refresh')} disabled={loading}>
        {loading ? ($language === 'zh' ? '刷新中…' : 'Refreshing...') : $t('file.refresh')}
      </button>
    </header>
    <div class="history-layout">
      <div class="history-list">
        {#if loading}
          <p class="muted">{$language === 'zh' ? '加载中…' : 'Loading...'}</p>
        {:else if !sessions.length}
          <p class="muted">{$t('sidebar.noSessions')}</p>
        {:else}
          <table>
            <thead>
              <tr>
                <th>{$language === 'zh' ? '会话' : 'Session'}</th>
                <th>{$language === 'zh' ? '事件数' : 'Events'}</th>
                <th>{$language === 'zh' ? '最近活动' : 'Last Activity'}</th>
                <th>{$language === 'zh' ? '操作' : 'Actions'}</th>
              </tr>
            </thead>
            <tbody>
              {#each sessions as sess (sess.session_id)}
                <tr class:selected={sess.session_id === selectedId}>
                  <td>
                    <button class="link" on:click={() => dispatch('preview', sess.session_id)}>
                      {sess.label ?? ($language === 'zh' ? '未命名会话' : 'Unnamed')}
                    </button>
                    <div class="muted mono">{sess.session_id}</div>
                  </td>
                  <td>{sess.events}</td>
                  <td>{formatTs(sess.last_event)}</td>
                  <td class="action-group">
                    <button class="ghost" on:click={() => dispatch('preview', sess.session_id)}>{$language === 'zh' ? '查看' : 'View'}</button>
                    <button class="ghost" on:click={() => dispatch('clone', sess.session_id)}>{$language === 'zh' ? '克隆' : 'Clone'}</button>
                    <button
                      class="danger ghost"
                      disabled={deletingId === sess.session_id}
                      on:click={() => dispatch('delete', sess.session_id)}
                    >
                      {deletingId === sess.session_id ? ($language === 'zh' ? '删除中…' : 'Deleting...') : $t('modal.delete')}
                    </button>
                  </td>
                </tr>
              {/each}
            </tbody>
          </table>
        {/if}
      </div>
      <div class="history-preview">
          <div class="contexts">
            <div class="context-header">
              <h4>{$t('history.contexts')}</h4>
              <button
                class="ghost warn small"
                disabled={!selectedId}
              on:click={() =>
                selectedId && dispatch('load', { id: selectedId, versionInput: '', tagInput: '', fromEvents: true })
              }
            >
              {$t('history.fromEvents')}
            </button>
          </div>
          {#if !selectedId}
            <p class="muted">{$language === 'zh' ? '选择会话以查看上下文版本。' : 'Select a session to view versions.'}</p>
          {:else if contextsLoading}
            <p class="muted">{$language === 'zh' ? '加载版本中…' : 'Loading versions...'}</p>
          {:else if !contexts.length}
            <p class="muted">{$t('history.noContexts')}</p>
          {:else}
            <ul class="context-list">
              {#each contexts as ctx (ctx.id ?? ctx.version)}
                {@const isActive = selectedId === currentSessionId && currentContextVersion === ctx.version}
                {@const isPreviewed = matchesPreviewContext(ctx.version, ctx.user_tag)}
                <li
                  class:is-active={isActive}
                  class:is-previewed={isPreviewed}
                >
                  <div class="context-meta">
                    <strong>{formatVersionLabel(ctx)}</strong>
                    {#if isActive}
                      <span class="badge">{$language === 'zh' ? '当前' : 'Active'}</span>
                    {/if}
                </div>
                <button
                  class="ghost"
                  type="button"
                  on:click={() =>
                    dispatch('contextPreview', { sessionId: selectedId, version: ctx.version, userTag: ctx.user_tag || undefined })
                  }
                >
                  {$language === 'zh' ? '预览' : 'Preview'}
                </button>
                <button
                  class="ghost"
                  type="button"
                  on:click={() =>
                    dispatch('load', { id: selectedId, versionInput: String(ctx.version), tagInput: ctx.user_tag || '', fromEvents: false })
                  }
                >
                  {$t('history.load')}
                </button>
                <button
                  class="ghost"
                  type="button"
                  on:click={() => dispatch('compress', { sessionId: selectedId, version: ctx.version, userTag: ctx.user_tag || undefined })}
                >
                  {$t('history.compress')}
                </button>
              </li>
            {/each}
          </ul>
        {/if}
      </div>
        <div class="events-preview">
          {#if !selectedId}
            <p class="muted">{$language === 'zh' ? '选择一条会话查看详情。' : 'Select a session for details.'}</p>
          {:else if contextPreviewMessages.length}
            <div class="preview-header">
              <div class="preview-titles">
                {#if previewContextLabel}
                  <p class="muted">{$language === 'zh' ? '预览版本：' : 'Previewing: '}{previewContextLabel}</p>
                {/if}
                {#if contextPreviewMeta?.created_at}
                  <p class="muted">{$language === 'zh' ? '创建时间：' : 'Created: '}{formatTs(contextPreviewMeta.created_at)}</p>
                {/if}
              </div>
              <div class="preview-meta">
                <span class="chip">{$language === 'zh' ? '消息 ' : 'Messages '}{contextPreviewMessages.length}</span>
                {#if contextPreviewMeta?.user_tag}
                  <span class="chip">{$t('history.tagLabel')} {contextPreviewMeta.user_tag}</span>
                {/if}
                {#each previewMetaChips as chip, idx (idx)}
                  <span class="chip">{chip}</span>
                {/each}
              </div>
            </div>
            <div class="context-preview-list">
              {#each contextPreviewMessages as msg, index (index)}
                {@const role = roleMetaFor(msg.role)}
                {@const toolCalls = toolCallsFrom(msg)}
                {@const textContent = textFromContent(msg.content)}
                {@const structured = structuredContent(msg.content)}
                {@const preferJson = msg.role === 'tool' && structured}
                <div class="context-card">
                  <div class="card-header">
                    <div class="card-title">
                      <span class="role-chip" style={`border-color:${role.color};color:${role.color};background:${role.color}22`}>
                        {role.label}
                      </span>
                      {#if msg.name}
                        <span class="mono muted">{msg.name}</span>
                      {/if}
                      {#if msg.tool_call_id}
                        <span class="mono muted">call_id: {msg.tool_call_id}</span>
                      {/if}
                      {#if toolCalls.length}
                        <span class="mono muted">{toolCalls.length} {$language === 'zh' ? '个工具调用' : 'tool calls'}</span>
                      {/if}
                    </div>
                    <small class="muted">#{index + 1}</small>
                  </div>

                  {#if toolCalls.length}
                    <div class="tool-call-list">
                      {#each toolCalls as tc, idx (tc.id ?? idx)}
                        <div class="tool-call">
                          <div class="tool-call-header">
                            <strong>{tc.name || ($language === 'zh' ? '调用' : 'Call')}</strong>
                            {#if tc.id}
                              <span class="mono muted">{tc.id}</span>
                            {/if}
                          </div>
                          {#if tc.parsedArgs}
                            <pre class="json-block">{@html highlightJson(tc.parsedArgs)}</pre>
                          {:else if tc.rawArgs}
                            <div class="content-block">{tc.rawArgs}</div>
                          {:else}
                            <p class="muted">{$language === 'zh' ? '无参数' : 'No args'}</p>
                          {/if}
                        </div>
                      {/each}
                    </div>
                  {/if}

                  {#if preferJson}
                    <pre class="json-block">{@html highlightJson(structured)}</pre>
                  {:else if textContent}
                    <div class={`content-block ${msg.role === 'system' ? 'system-block' : ''}`}>
                      {@html renderMarkdown(textContent)}
                    </div>
                  {:else if structured}
                    <pre class="json-block">{@html highlightJson(structured)}</pre>
                  {:else}
                    <p class="muted">{$language === 'zh' ? '无可展示内容' : 'No content'}</p>
                  {/if}
                </div>
              {/each}
            </div>
          {:else}
            <p class="muted">{$language === 'zh' ? '点击左侧上下文版本以预览。' : 'Select a version to preview.'}</p>
          {/if}
        </div>
      </div>
    </div>
    <footer class="modal-actions">
      <button class="ghost" on:click={() => dispatch('close')}>{$t('modal.close')}</button>
    </footer>
  </div>
</div>

<style>
.history-layout {
  display: grid;
  grid-template-columns: 1.2fr 1.8fr;
  gap: 16px;
  height: 75vh;
  min-height: 60vh;
}

:global(.modal.wide) {
  width: min(1650px, 95vw);
}

.history-list {
  border: 1px solid #1f2a37;
  border-radius: 12px;
  padding: 12px;
  overflow: auto;
  height: 100%;
  min-height: 0;
}

.history-preview {
  border: 1px solid #1f2a37;
  border-radius: 12px;
  padding: 12px;
  display: grid;
  grid-template-columns: minmax(320px, 1.2fr) 3fr;
  gap: 12px;
  height: 100%;
  min-height: 0;
}

table {
  width: 100%;
  border-collapse: collapse;
}
th,
td {
  padding: 8px;
  text-align: left;
  border-bottom: 1px solid #1f2a37;
}
tr.selected {
  background: #111b2a;
}
button.link {
  background: none;
  border: none;
  color: #4c6ef5;
  cursor: pointer;
  padding: 0;
}
.contexts {
  border-right: 1px solid #1f2a37;
  padding-right: 8px;
  overflow: auto;
  min-width: 320px;
}
.context-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 6px;
}
.context-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.context-list li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #0b121a;
  border: 1px solid #1f2a37;
  border-radius: 10px;
  padding: 8px 10px;
  gap: 8px;
}
.context-list li.is-active {
  border-color: #1f2a37;
  box-shadow: none;
}
.context-list li.is-previewed {
  border-color: #4c6ef5;
  box-shadow: 0 0 0 1px #4c6ef522;
}
.context-meta {
  display: flex;
  align-items: center;
  gap: 8px;
}
.badge {
  display: inline-block;
  padding: 2px 6px;
  border-radius: 6px;
  background: #4c6ef522;
  color: #c7d2fe;
  border: 1px solid #4c6ef5;
  font-size: 12px;
}
.ghost.small {
  padding: 4px 8px;
  font-size: 12px;
}
.events-preview {
  overflow: auto;
  height: 100%;
  min-height: 0;
}
.muted.mono {
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
}
.mono {
  font-family: 'JetBrains Mono', monospace;
}
.action-group {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.preview-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}
.preview-titles p {
  margin: 0;
}
.preview-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.context-preview-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.context-card {
  background: #0b121a;
  border: 1px solid #1f2a37;
  border-radius: 12px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.role-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid #4c6ef5;
  background: #111b2a;
  font-size: 12px;
  font-weight: 600;
}
.content-block {
  border: 1px solid #1f2a37;
  border-radius: 10px;
  padding: 8px 10px;
  background: #0f172a;
  white-space: pre-wrap;
  word-break: break-word;
}
.content-block :global(p) {
  margin: 0 0 6px;
}
.content-block :global(p:last-child) {
  margin-bottom: 0;
}
.system-block {
  border-color: #4c6ef5;
  background: #111b2a;
}
.tool-call-list {
  border: 1px dashed #1f2a37;
  border-radius: 10px;
  padding: 8px 10px;
  background: #0f172a;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.tool-call {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.tool-call-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
</style>
