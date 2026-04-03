<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import { language, t } from '../lib/i18n';

  export let activeLabel: string | null = null;
  export let pendingCount = 0;
  export let exporting = false;
  export let exportingHtml = false;
  export let canExport = true;
  export let canClose = false;
  export let contextVersion: number | null = null;
  export let contextTag: string | null = null;

  const dispatch = createEventDispatcher<{
    refresh: void;
    files: void;
    history: void;
    close: void;
    export: void;
    exportHtml: void;
    logs: void;
    create: void;
  }>();

  function toggleLanguage() {
    language.update(l => l === 'zh' ? 'en' : 'zh');
  }
</script>

<header class="topbar">
  <div class="brand">
    <span class="logo">⧉</span>
    <div>
      <strong>Re-Re-MA Console</strong>
      <div class="muted">{$language === 'zh' ? '多智能体协作 · 审计可追溯' : 'Multi-Agent · Audit Traceable'}</div>
    </div>
  </div>
  <div class="topbar-chips">
    <div class="chip">
      {$language === 'zh' ? '当前会话：' : 'Session: '}
      {#if activeLabel}
        {activeLabel}
      {:else}
        {$t('topbar.noActiveSession')}
      {/if}
    </div>
    <div class={`chip ${pendingCount ? 'warn' : ''}`}>
      {$t('status.pending')}：{pendingCount}
    </div>
    <div class="chip">
      {$language === 'zh' ? '上下文：' : 'Context: '}
      {contextVersion ? `v${contextVersion}` : ($language === 'zh' ? '最新' : 'Latest')}
      {#if contextTag}
        <span class="muted">· {contextTag}</span>
      {/if}
    </div>
  </div>
  <div class="spacer" />
  
  <button class="ghost lang-btn" on:click={toggleLanguage}>
    {$language === 'zh' ? 'English' : '中文'}
  </button>

  <button class="ghost" on:click={() => dispatch('refresh')}>{$t('topbar.refresh')}</button>
  <button class="ghost" on:click={() => dispatch('files')}>{$t('topbar.files')}</button>
  <button class="ghost" on:click={() => dispatch('history')}>{$t('topbar.history')}</button>
  <button class="ghost" on:click={() => dispatch('close')} disabled={!canClose}>{$t('topbar.close')}</button>
  <button class="ghost" on:click={() => dispatch('export')} disabled={!canExport || exporting}>
    {exporting ? ($language === 'zh' ? '导出中...' : 'Exporting...') : $t('topbar.exportPdf')}
  </button>
  <button class="ghost" on:click={() => dispatch('exportHtml')} disabled={!canExport || exportingHtml}>
    {exportingHtml ? ($language === 'zh' ? '导出中...' : 'Exporting...') : $t('topbar.exportHtml')}
  </button>
  <button class="ghost" on:click={() => dispatch('logs')}>{$t('topbar.logs')}</button>
  <button class="accent" on:click={() => dispatch('create')}>＋ {$t('topbar.create')}</button>
</header>

<style>
  .lang-btn {
    border: 1px solid var(--border);
    margin-right: 8px;
    font-size: 0.9em;
  }
</style>
