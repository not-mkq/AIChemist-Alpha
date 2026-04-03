<script lang="ts">
  import { afterUpdate, createEventDispatcher } from 'svelte';
  import type { TimelineEvent, WorkspaceFile, FileValidationRules, FileTask } from '../lib/types';
  import { auditIdOfEvent, eventMeta, highlightJson, linkFilesInText, renderMarkdown } from '../lib/utils';
  import { uploadSessionFile, notifyFileAgentUpload } from '../lib/api';
  import { t, language } from '../lib/i18n';

export let events: TimelineEvent[] = [];
export let activeSessionId: string | null = null;
export let message = '';
export let sending = false;
export let workspaceFiles: WorkspaceFile[] = [];
export let thinkMode = false;

  const dispatch = createEventDispatcher<{ send: void; preview: string }>();
  let timelineEl: HTMLElement | null = null;
  let shouldStickBottom = true;
  let lastEventCount = 0;
  let expandedDrafts: Record<string, boolean> = {};
  let uploadStates: Record<
    string,
    {
      status: 'idle' | 'pending_audit' | 'uploading' | 'validating' | 'done' | 'error';
      message?: string;
      filename?: string;
      result?: Record<string, unknown>;
      errors?: string[];
    }
  > = {};

  function handleScroll() {
    if (!timelineEl) return;
    const threshold = 40;
    const distance =
      timelineEl.scrollHeight - timelineEl.scrollTop - timelineEl.clientHeight;
    shouldStickBottom = distance < threshold;
  }

  function maybeScroll() {
    if (shouldStickBottom && timelineEl) {
      timelineEl.scrollTo({ top: timelineEl.scrollHeight, behavior: 'smooth' });
    }
  }

  afterUpdate(() => {
    if (events.length !== lastEventCount) {
      maybeScroll();
      lastEventCount = events.length;
    }
  });

  function handleWorkspaceAnchor(anchor: HTMLAnchorElement, event: Event) {
    const href = anchor.getAttribute('href');
    if (href && href.startsWith('workspace://')) {
      event.preventDefault();
      const path = decodeURIComponent(href.replace('workspace://', ''));
      dispatch('preview', path);
    }
  }

  function workspaceLink(node: HTMLElement) {
    const handleClick = (event: MouseEvent) => {
      const target = event.target as HTMLElement;
      const anchor = target.closest('a');
      if (!anchor) return;
      handleWorkspaceAnchor(anchor as HTMLAnchorElement, event);
    };
    node.addEventListener('click', handleClick);
    return {
      destroy() {
        node.removeEventListener('click', handleClick);
      },
    };
  }

  function send() {
    dispatch('send');
  }

  const payloadOf = (evt: TimelineEvent) => evt.payload ?? {};
  const argumentsOf = (evt: TimelineEvent) => {
    const payload = payloadOf(evt);
    const args = (payload.arguments as Record<string, unknown>) ?? evt.arguments ?? {};
    return args as Record<string, unknown>;
  };
  // file_service 的 tool_result 直接展示 JSON 即可，这里不再从中派生上传任务。

  const taskFromPromptPayload = (payload: Record<string, unknown> | null | undefined): FileTask | null => {
    if (!payload) return null;
    const raw = (payload as any).task;
    if (!raw || typeof raw !== 'object') return null;
    return raw as FileTask;
  };

  function auditStatusFor(toolName: string | undefined, args: Record<string, unknown>) {
    const key = JSON.stringify(args || {});
    let status: 'pending_audit' | 'approved' | 'rejected' | 'unknown' = 'unknown';
    for (const evt of events) {
      const t = evt.raw_type || evt.type;
      const p = payloadOf(evt);
      if (t === 'audit_request' && p.tool_name === toolName && JSON.stringify(p.arguments ?? {}) === key) {
        status = 'pending_audit';
      }
      if (t === 'audit_decision' && p.tool_name === toolName && JSON.stringify(p.arguments ?? {}) === key) {
        status = p.approved ? 'approved' : 'rejected';
      }
    }
    return status;
  }

  const contentOf = (evt: TimelineEvent) => {
    const direct = typeof evt.content === 'string' ? evt.content : null;
    if (direct) return direct;
    const payload = payloadOf(evt);
    const inner = payload.content;
    return typeof inner === 'string' ? inner : '';
  };

  function isDraftContent(content: string | undefined, flags?: Record<string, unknown> | null) {
    if (flags && typeof flags.draft === 'boolean') {
      return Boolean(flags.draft);
    }
    return Boolean(content && (content.includes('【思考草稿】') || content.includes('[Thought Draft]')));
  }

  function toggleDraft(key: string) {
    expandedDrafts = { ...expandedDrafts, [key]: !expandedDrafts[key] };
  }

  function draftKey(evt: TimelineEvent, index: number) {
    const base = evt.id ?? evt.index ?? `${evt.timestamp}-${evt.type}-${index}`;
    return String(base);
  }

  const formatValidationRules = (rules: unknown) => {
    const typed = rules as FileValidationRules | undefined;
    if (!typed) return [];
    const chips: string[] = [];
    const isZh = $language === 'zh';
    if (typed.allowed_extensions?.length) {
      chips.push((isZh ? '允许后缀: ' : 'Allowed: ') + typed.allowed_extensions.join(', '));
    }
    if (typed.csv_headers?.length) {
      chips.push((isZh ? '表头需匹配: ' : 'Headers: ') + typed.csv_headers.join(', '));
    }
    if (typed.csv_min_rows != null || typed.csv_max_rows != null) {
      chips.push((isZh ? '行数: ' : 'Rows: ') + `${typed.csv_min_rows ?? 0} - ${typed.csv_max_rows ?? '∞'}`);
    }
    if (typed.csv_min_cols != null || typed.csv_max_cols != null) {
      chips.push((isZh ? '列数: ' : 'Cols: ') + `${typed.csv_min_cols ?? 0} - ${typed.csv_max_cols ?? '∞'}`);
    }
    return chips;
  };

  async function handleUpload(evt: Event, key: string, args: Record<string, unknown>, task?: FileTask) {
    const input = evt.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file || !activeSessionId) return;
    const isZh = $language === 'zh';
    uploadStates = {
      ...uploadStates,
      [key]: { status: 'uploading', message: isZh ? '上传中…' : 'Uploading...' },
    };
    try {
      const uploaded = await uploadSessionFile(activeSessionId, file, {
        taskId: task?.task_id ?? key,
        targetPath: (args.filename as string | undefined) ?? undefined,
      });
      const workspacePath = uploaded.path ?? uploaded.name ?? file.name;
      uploadStates = {
        ...uploadStates,
        [key]: { status: 'validating', message: isZh ? '校验中…' : 'Validating...', filename: workspacePath },
      };

      // step 8: 前端告知 file_agent 用户上传的文件（而不是后端）
      await notifyFileAgentUpload(task?.task_id ?? key, {
        workspacePath,
        userFilename: uploaded.user_filename ?? file.name,
        overwritten: uploaded.overwritten,
      });

      uploadStates = {
        ...uploadStates,
        [key]: {
          status: 'done',
          filename: workspacePath,
          result: undefined,
          errors: [],
          message: isZh ? '已通知校验，等待结果…' : 'Validation requested...',
        },
      };
    } catch (error) {
      const message = error instanceof Error ? error.message : (isZh ? '上传或校验失败' : 'Upload failed');
      uploadStates = { ...uploadStates, [key]: { status: 'error', message } };
    } finally {
      input.value = '';
    }
  }
</script>

<div class="conversation-pane">
  <section class="timeline" bind:this={timelineEl} on:scroll={handleScroll}>
    {#if !activeSessionId}
      <div class="empty-card">{$language === 'zh' ? '请选择一个会话开始监控。' : 'Select a session to start.'}</div>
    {:else if events.length === 0}
      <div class="empty-card">{$t('chat.noEvents')}</div>
    {:else}
      {#each events as evt, i (evt.id ?? `${evt.timestamp}-${(evt.raw_type || evt.type)}-${auditIdOfEvent(evt) ?? i}`)}
        {@const meta = eventMeta(evt, $language)}
        {@const payload = payloadOf(evt)}
        {@const content = contentOf(evt)}
        {#if meta}
          <article class="event-card" style={`border-left-color:${meta.color}`}>
            <div class="avatar" style={`border-color:${meta.color};background:${meta.color}22`}>
              {meta.icon}
            </div>
            <div class="event-body">
              <div class="event-header">
                <div>
                  <div class="event-title">
                    {meta.label}
                    {#if meta.subtitle}
                      <span class="subtitle">· {meta.subtitle}</span>
                    {/if}
                  </div>
                  {#if meta.hint}
                    <small class="muted">{meta.hint}</small>
                  {/if}
                </div>
                <div class="event-meta">
                  <span class="tag" style={`border-color:${meta.color};color:${meta.color}`}>{meta.label}</span>
                  <span class="muted">#{i + 1}</span>
                </div>
              </div>

              {#if (evt.raw_type || evt.type) === 'system_prompt'}
                <div class="system-chip">{content}</div>
              {:else if (evt.raw_type || evt.type) === 'user_message'}
                <div class="markdown" use:workspaceLink>
                  {@html renderMarkdown(linkFilesInText(content, workspaceFiles))}
                </div>
              {:else if (evt.raw_type || evt.type) === 'assistant_message' && isDraftContent(content, evt.flags)}
                <div class="thinking-block">
                  <button class="thinking-toggle" on:click={() => toggleDraft(draftKey(evt, i))}>
                    {expandedDrafts[draftKey(evt, i)] 
                      ? ($language === 'zh' ? '收起思考草稿' : 'Hide Thought Draft') 
                      : ($language === 'zh' ? '查看思考草稿' : 'View Thought Draft')}
                  </button>
                  {#if expandedDrafts[draftKey(evt, i)]}
                    <div class="markdown" use:workspaceLink>
                      {@html renderMarkdown(linkFilesInText(content, workspaceFiles))}
                    </div>
                  {/if}
                </div>
              {:else if (evt.raw_type || evt.type) === 'assistant_message'}
                <div class="markdown" use:workspaceLink>
                  {@html renderMarkdown(linkFilesInText(content, workspaceFiles))}
                </div>
              {:else if meta.body}
                <p class="event-text">{meta.body}</p>
              {/if}

              {#if (evt.raw_type || evt.type) === 'file_upload_prompt'}
                {@const task = taskFromPromptPayload(payload)}
                {@const key = task?.task_id ?? draftKey(evt, i)}
                {@const ruleChips = formatValidationRules(task?.validation)}
                <div class="upload-card">
                  <div class="upload-header">
                    <strong>{$language === 'zh' ? '文件上传校验' : 'File Upload & Validation'}</strong>
                    <span class="tag warning">{$language === 'zh' ? '待上传' : 'Pending'}</span>
                  </div>
                  <p class="muted">{$language === 'zh' ? 'AI 请求上传并校验文件，请选择要上传的文件。' : 'AI requested a file upload for validation. Please choose a file.'}</p>
                  {#if ruleChips.length}
                    <div class="chips">
                      {#each ruleChips as chip, idx (idx)}
                        <span class="chip ghost">{chip}</span>
                      {/each}
                    </div>
                  {/if}
                    <label class="upload-btn">
                      {$language === 'zh' ? '选择文件' : 'Choose File'}
                      <input
                        type="file"
                        disabled={uploadStates[key]?.status === 'done'}
                        on:change={(e) =>
                          handleUpload(e, key, { validation: task?.validation, filename: task?.filename }, task ?? undefined)}
                      />
                    </label>
                  {#if uploadStates[key]}
                    <div class={`upload-status ${uploadStates[key].status}`}>
                      <div>{uploadStates[key].message}</div>
                      {#if uploadStates[key].filename}
                        <div class="muted">{$language === 'zh' ? '文件：' : 'File: '}{uploadStates[key].filename}</div>
                      {/if}
                      {#if uploadStates[key].errors && uploadStates[key].errors.length}
                        <ul class="error-list">
                          {#each uploadStates[key].errors as err, idx (idx)}
                            <li>{err}</li>
                          {/each}
                        </ul>
                      {/if}
                      {#if uploadStates[key].status === 'done' && (!uploadStates[key].errors || uploadStates[key].errors.length === 0)}
                        <div class="muted">{$language === 'zh' ? '校验通过。' : 'Validation passed.'}</div>
                      {/if}
                    </div>
                  {/if}
                </div>
              {/if}

              {#if (evt.raw_type || evt.type) === 'file_upload_done'}
                <div class="upload-card">
                  <div class="upload-header">
                    <strong>{$language === 'zh' ? '文件已上传' : 'File Uploaded'}</strong>
                    <span class="tag success">{$language === 'zh' ? '完成' : 'Done'}</span>
                  </div>
                  <p class="muted">
                    {payload.user_filename || payload.name} {$language === 'zh' ? '已保存为' : 'saved as'} {payload.path}
                    {#if payload.overwritten}
                      （{$language === 'zh' ? '覆盖同名文件' : 'overwritten'}）
                    {/if}
                  </p>
                  {#if payload.download_url}
                    <a class="chip ghost" href={String(payload.download_url)} target="_blank" rel="noreferrer">{$language === 'zh' ? '下载' : 'Download'}</a>
                  {/if}
                </div>
              {/if}

              {#if (evt.raw_type || evt.type) === 'audit_decision' && payload.analysis}
                <div class="analysis-block">
                  <strong>AI {$language === 'zh' ? '分析' : 'Analysis'}</strong>
                  <p>{payload.analysis?.analysis}</p>
                  {#if payload.analysis?.possible_causes?.length}
                    <div class="chips">
                      {#each payload.analysis.possible_causes as cause, idx (idx)}
                        <span class="chip ghost">{cause}</span>
                      {/each}
                    </div>
                  {/if}
                  {#if payload.analysis?.recommendations?.length}
                    <small>{$language === 'zh' ? '建议：' : 'Recs:'}</small>
                    <ul>
                      {#each payload.analysis.recommendations as rec, idx (idx)}
                        <li>{rec}</li>
                      {/each}
                    </ul>
                  {/if}
                </div>
              {/if}

              {#if (evt.raw_type || evt.type) === 'tool_call'}
                <pre class="json-block">{@html highlightJson(payload.arguments)}</pre>
              {/if}
              {#if (evt.raw_type || evt.type) === 'tool_result'}
                <pre class="json-block">{@html highlightJson(payload.result)}</pre>
              {/if}
              {#if (evt.raw_type || evt.type) === 'audit_request' && payload.ai_decision?.doubts?.length}
                <ul class="doubt-list">
                  {#each payload.ai_decision.doubts as doubt, idx (idx)}
                    <li>• {doubt}</li>
                  {/each}
                </ul>
              {/if}
            </div>
          </article>
        {/if}
      {/each}
    {/if}
  </section>

  {#if activeSessionId}
    <section class="composer">
      <textarea
        placeholder={$language === 'zh' ? '输入指令，Shift + Enter 换行' : 'Type commands, Shift + Enter for new line'}
        bind:value={message}
        rows="3"
        on:keydown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            send();
          }
        }}
      />
      <div class="composer-actions">
        <label class="think-toggle">
          <input type="checkbox" bind:checked={thinkMode} />
          <span>{$t('chat.thinkMode')}</span>
        </label>
        <button class="accent" on:click={send} disabled={sending}>
          {sending ? $t('chat.sending') : $t('chat.send')}
        </button>
      </div>
    </section>
  {/if}
</div>
