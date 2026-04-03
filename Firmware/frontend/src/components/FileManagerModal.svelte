<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import type { WorkspaceFile } from '../lib/types';
  import { t, language } from '../lib/i18n';

  export let files: WorkspaceFile[] = [];

  const dispatch = createEventDispatcher<{
    close: void;
    refresh: void;
    preview: string;
  }>();
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
  <div class="modal info file-manager" role="dialog" aria-modal="true">
    <div class="file-manager-header">
      <h3>{$t('file.manager')}</h3>
      <button class="ghost" on:click={() => dispatch('refresh')}>{$t('file.refresh')}</button>
    </div>
    {#if files.length === 0}
      <p class="muted">{$language === 'zh' ? '当前工作区暂无文件。' : 'No files in workspace.'}</p>
    {:else}
      <table class="file-table">
        <thead>
          <tr>
            <th>{$t('file.name')}</th>
            <th>{$t('file.size')}</th>
            <th>{$language === 'zh' ? '类型' : 'Type'}</th>
            <th>{$language === 'zh' ? '操作' : 'Actions'}</th>
          </tr>
        </thead>
        <tbody>
          {#each files as file (file.path)}
            <tr>
              <td>{file.path}</td>
              <td>{file.size} B</td>
              <td>{file.type}</td>
              <td>
                <button class="action-btn secondary" on:click={() => dispatch('preview', file.path)}>
                  {$t('file.preview')}
                </button>
                <a
                  class="action-btn"
                  href={`/api/workspace/file/download?path=${encodeURIComponent(file.path)}`}
                  download
                >
                  {$language === 'zh' ? '下载' : 'Download'}
                </a>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}
    <div class="modal-actions">
      <button class="ghost" on:click={() => dispatch('close')}>{$t('modal.close')}</button>
    </div>
  </div>
</div>
