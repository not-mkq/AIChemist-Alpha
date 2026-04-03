<script lang="ts">
  import { afterUpdate, createEventDispatcher } from 'svelte';
  import type { AuditBundle, AuditDecisionInfo, TimelineEvent } from '../lib/types';
  import { formatTime, riskClass, toolResultPayload } from '../lib/utils';
  import { t, language } from '../lib/i18n';

  export let pendingAudits: AuditBundle[] = [];
  export let auditHistory: AuditBundle[] = [];
  export let noteMap: Record<string, string> = {};
  export let pendingActionId: string | null = null;
  export let actionType: 'approve' | 'reject' | null = null;

  const dispatch = createEventDispatcher<{
    audit: { decision: 'approve' | 'reject'; id: string };
    note: { id: string; value: string };
  }>();

  let paneEl: HTMLElement | null = null;
  let stickTop = true;
  let lastCounts = { pending: 0, history: 0 };

  function handleScroll() {
    if (!paneEl) return;
    const threshold = 20;
    stickTop = paneEl.scrollTop <= threshold;
  }

  function maybeScrollTop() {
    if (stickTop && paneEl) {
      paneEl.scrollTo({ top: 0, behavior: 'smooth' });
    }
  }

  afterUpdate(() => {
    if (
      pendingAudits.length !== lastCounts.pending ||
      auditHistory.length !== lastCounts.history
    ) {
      maybeScrollTop();
      lastCounts = { pending: pendingAudits.length, history: auditHistory.length };
    }
  });

  const getNote = (id: string) => noteMap[id] ?? '';

  const toRecord = (value: unknown): Record<string, unknown> | undefined => {
    if (!value || typeof value !== 'object') return undefined;
    return value as Record<string, unknown>;
  };
  const asString = (value: unknown): string | undefined => {
    if (typeof value !== 'string') return undefined;
    const trimmed = value.trim();
    return trimmed ? trimmed : undefined;
  };
  const payloadOf = (evt?: TimelineEvent | null) => evt?.payload ?? {};

  const severityMeta = (score?: number, lang: 'zh' | 'en' = 'zh') => {
    if (score === undefined || score === null) {
      return { level: 'risk-neutral', label: lang === 'zh' ? '待评估' : 'Pending' };
    }
    if (score >= 70) {
      return { level: 'risk-high', label: lang === 'zh' ? '高危操作' : 'High Risk' };
    }
    if (score >= 40) {
      return { level: 'risk-mid', label: lang === 'zh' ? '中等风险' : 'Mid Risk' };
    }
    return { level: 'risk-low', label: lang === 'zh' ? '低风险' : 'Low Risk' };
  };

  const toolNameFromEvent = (evt?: TimelineEvent) => {
    if (!evt) return undefined;
    if (evt.tool_name) return evt.tool_name;
    if (evt.tool) return evt.tool;
    const payload = payloadOf(evt);
    return (payload.tool_name as string) ?? (payload.tool as string);
  };

  const toolNameOf = (bundle: AuditBundle) =>
    toolNameFromEvent(bundle.request) ??
    toolNameFromEvent(bundle.decision) ??
    toolNameFromEvent(bundle.toolResult) ??
    ($language === 'zh' ? '未命名工具' : 'Unnamed Tool');

  const aiDecisionOf = (bundle: AuditBundle): AuditDecisionInfo | undefined => {
    if (!bundle.request) return undefined;
    if (bundle.request.ai_decision) return bundle.request.ai_decision;
    const payload = payloadOf(bundle.request);
    return payload.ai_decision as AuditDecisionInfo | undefined;
  };

  const riskScoreOf = (bundle: AuditBundle) => {
    const request = bundle.request;
    if (typeof request?.risk_score === 'number') return request.risk_score;
    const payload = payloadOf(request);
    if (typeof (payload as Record<string, unknown>).risk_score === 'number') {
      return payload.risk_score as number;
    }
    return aiDecisionOf(bundle)?.risk_score;
  };

  const argsOf = (bundle: AuditBundle) => {
    const direct = bundle.request?.arguments;
    if (direct && Object.keys(direct).length) return direct;
    const payload = payloadOf(bundle.request);
    const args = payload.arguments as Record<string, unknown> | undefined;
    if (args && Object.keys(args).length) return args;
    return undefined;
  };

  const requestTime = (bundle: AuditBundle) =>
    bundle.request ? formatTime(bundle.request.timestamp) : null;

  const decisionTime = (bundle: AuditBundle) =>
    bundle.decision ? formatTime(bundle.decision.timestamp) : null;

  const decisionApproved = (bundle: AuditBundle) => {
    const decision = bundle.decision;
    if (!decision) return undefined;
    if (typeof decision.approved === 'boolean') return decision.approved;
    const payload = payloadOf(decision);
    const approved = payload.approved;
    return typeof approved === 'boolean' ? approved : undefined;
  };

  const decisionNote = (bundle: AuditBundle) => {
    const decision = bundle.decision;
    if (!decision) return undefined;
    if (typeof decision.note === 'string' && decision.note.trim()) return decision.note.trim();
    const payload = payloadOf(decision);
    const note = payload.note;
    return typeof note === 'string' && note.trim() ? note.trim() : undefined;
  };

  const decisionAnalysisText = (bundle: AuditBundle) => {
    const decision = bundle.decision;
    if (!decision) return undefined;
    if (decision.analysis?.analysis) return decision.analysis.analysis;
    const payload = payloadOf(decision);
    const analysis = toRecord(payload.analysis);
    const text = analysis?.analysis;
    return typeof text === 'string' ? text : undefined;
  };

  type ResultDetails = {
    summary?: string;
    error?: string;
    analysis?: string;
    userNote?: string;
  };

  const resultDetails = (bundle: AuditBundle): ResultDetails | null => {
    const event = bundle.toolResult;
    if (!event) return null;
    const result = toolResultPayload(event);
    if (!result) return null;
    const detail = toRecord(result.detail);
    const analysis = toRecord(detail?.analysis);
    const summary =
      asString(detail?.ai_summary) ??
      asString(result.reason) ??
      asString(result.output) ??
      asString(result.message);
    const error = asString(result.error);
    const analysisText = asString(analysis?.analysis);
    const userNote = asString(detail?.user_note) ?? asString(detail?.note);
    if (!summary && !error && !analysisText && !userNote) {
      return null;
    }
    return {
      summary,
      error,
      analysis: analysisText,
      userNote,
    };
  };

  const historyStatus = (bundle: AuditBundle, lang: 'zh' | 'en' = 'zh') => {
    const approved = decisionApproved(bundle);
    if (approved === true) {
      return { 
        label: lang === 'zh' ? '已通过' : 'Approved', 
        tone: 'success', 
        icon: '✅', 
        description: lang === 'zh' ? '调用已通过' : 'Call approved' 
      };
    }
    if (approved === false) {
      return { 
        label: lang === 'zh' ? '已拒绝' : 'Rejected', 
        tone: 'danger', 
        icon: '⛔', 
        description: lang === 'zh' ? '调用被拒绝' : 'Call rejected' 
      };
    }
    const result = resultDetails(bundle);
    if (result?.error) {
      return { 
        label: lang === 'zh' ? '已拒绝' : 'Rejected', 
        tone: 'danger', 
        icon: '⛔', 
        description: result.error 
      };
    }
    return { 
      label: lang === 'zh' ? '已完成' : 'Done', 
      tone: 'info', 
      icon: '🛡️', 
      description: lang === 'zh' ? '工具调用完成' : 'Tool call complete' 
    };
  };

  const aiDoubts = (bundle: AuditBundle) => {
    const decision = aiDecisionOf(bundle);
    if (!decision?.doubts?.length) return [];
    return decision.doubts.filter((doubt) => typeof doubt === 'string' && doubt.trim());
  };

  const pendingSummary = (bundle: AuditBundle) => {
    const decision = aiDecisionOf(bundle);
    return decision?.summary;
  };
</script>

<aside class="audit-pane" bind:this={paneEl} on:scroll={handleScroll}>
  <div class="audit-header">
    <h3>{$t('audit.pending')}</h3>
    <span class="chip warn">{$language === 'zh' ? '待处理：' : 'Pending: '}{pendingAudits.length}</span>
  </div>

  <div class="audit-section compact">
    <h4>{$t('audit.pending')}</h4>
    {#if !pendingAudits.length}
      <p class="muted">{$t('audit.noPending')}</p>
    {:else}
      {#each pendingAudits as audit, index (audit.id)}
        {@const riskScore = riskScoreOf(audit)}
        {@const severity = severityMeta(riskScore, $language)}
        {@const order = pendingAudits.length - index}
        {@const summary = pendingSummary(audit)}
        {@const doubts = aiDoubts(audit)}
        {@const args = argsOf(audit)}
        <div class={`audit-card ${severity.level} ${riskClass(riskScore)}`}>
          <div class="audit-avatar">🛡️</div>
          <div class="audit-content">
            <div class="audit-title">
              <span>{toolNameOf(audit)}</span>
              <small># {order}</small>
            </div>
            <div class="meta-row">
              {#if requestTime(audit)}
                <small>{$language === 'zh' ? '请求时间：' : 'Requested: '}{requestTime(audit)}</small>
              {/if}
              <span class={`risk-chip ${severity.level}`}>{severity.label}</span>
            </div>
            {#if summary}
              <p>{summary}</p>
            {/if}
            {#if doubts.length}
              <ul>
                {#each doubts as doubt, idx (idx)}
                  <li>{doubt}</li>
                {/each}
              </ul>
            {/if}
            {#if args}
              <div class="arguments-block">
                <strong>{$language === 'zh' ? '调用参数' : 'Parameters'}</strong>
                <pre>{JSON.stringify(args, null, 2)}</pre>
              </div>
            {/if}
            <textarea
              placeholder={$t('audit.notePlaceholder')}
              value={getNote(audit.id)}
              on:input={(e) => dispatch('note', { id: audit.id, value: e.currentTarget.value })}
            ></textarea>
            <div class="audit-actions">
              <button
                class={`danger ${pendingActionId === audit.id && actionType === 'reject' ? 'processing' : ''}`}
                on:click={() => dispatch('audit', { decision: 'reject', id: audit.id })}
              >
                {pendingActionId === audit.id && actionType === 'reject' ? ($language === 'zh' ? '处理中...' : 'Proc...') : $t('audit.reject')}
              </button>
              <button
                class={`primary ${pendingActionId === audit.id && actionType === 'approve' ? 'processing' : ''}`}
                on:click={() => dispatch('audit', { decision: 'approve', id: audit.id })}
              >
                {pendingActionId === audit.id && actionType === 'approve' ? ($language === 'zh' ? '处理中...' : 'Proc...') : $t('audit.approve')}
              </button>
            </div>
          </div>
        </div>
      {/each}
    {/if}
  </div>

  <div class="audit-section compact">
    <h4>{$t('audit.history')}</h4>
    {#if !auditHistory.length}
      <p class="muted">{$t('audit.noHistory')}</p>
    {:else}
      {#each auditHistory as item, index (item.id)}
        {@const riskScore = riskScoreOf(item)}
        {@const severity = severityMeta(riskScore, $language)}
        {@const status = historyStatus(item, $language)}
        {@const info = resultDetails(item)}
        {@const summary = pendingSummary(item)}
        {@const doubts = aiDoubts(item)}
        <div class={`audit-card small ${severity.level}`}>
          <div class="audit-avatar">{status.icon}</div>
          <div class="audit-content">
            <div class="audit-title">
              <span>{toolNameOf(item)}</span>
              <small># {auditHistory.length - index}</small>
            </div>
            <div class="meta-row">
              <span class={`status-chip ${status.tone}`}>{status.label}</span>

            </div>
            <div class="audit-subsection">
              <strong>{$language === 'zh' ? '审核结论' : 'Audit Conclusion'}</strong>
              {#if item.decision}
                <p>
                  {status.description}
                  {decisionNote(item) ? ` · ${decisionNote(item)}` : ''}
                </p>
                {#if decisionAnalysisText(item)}
                  <p class="muted">{decisionAnalysisText(item)}</p>
                {/if}
              {:else if info?.userNote}
                <p>{$language === 'zh' ? '备注：' : 'Note: '}{info.userNote}</p>
              {:else}
                <p class="muted">{$language === 'zh' ? '工具自动结束，未记录人工结论。' : 'Tool ended automatically, no user conclusion.'}</p>
              {/if}
              {#if summary}
                <p>{summary}</p>
              {/if}
              {#if doubts.length}
                <ul>
                  {#each doubts as doubt, idx (idx)}
                    <li>{doubt}</li>
                  {/each}
                </ul>
              {/if}
            </div>
          </div>
        </div>
      {/each}
    {/if}
  </div>
</aside>
