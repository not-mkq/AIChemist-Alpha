<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import type { WorkspacePreview } from '../lib/types';
  import { t, language } from '../lib/i18n';

  export let file: WorkspacePreview;

  const dispatch = createEventDispatcher<{ close: void }>();
</script>

<div
  class="modal-backdrop topmost"
  role="presentation"
  tabindex="-1"
  on:click={(event) => {
    if (event.target === event.currentTarget) dispatch('close');
  }}
  on:keydown={(event) => {
    if (event.key === 'Escape') dispatch('close');
  }}
>
  <div class="modal info" role="dialog" aria-modal="true">
    <h3>{$t('file.preview')} · {file.name}</h3>
    <div class="muted">
      {$language === 'zh' ? '路径：' : 'Path: '}{file.path} · 
      {$language === 'zh' ? '大小：' : 'Size: '}{file.size} B
    </div>
    {#if file.type === 'text'}
      <pre>{file.content}</pre>
    {:else if file.type === 'image' && file.content_base64}
      <img src={file.content_base64} alt={file.name} class="preview-image" />
    {:else}
      <p class="muted">{$language === 'zh' ? '该类型暂不支持直接预览，请下载查看。' : 'Preview not supported for this type. Please download to view.'}</p>
    {/if}
    <div class="modal-actions">
      <a class="action-btn" href={`/api${file.download_url}`} download>{$language === 'zh' ? '下载' : 'Download'}</a>
      <button class="action-btn secondary" on:click={() => dispatch('close')}>{$t('modal.close')}</button>
    </div>
  </div>
</div>
