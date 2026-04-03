<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import type { AgentCard, AgentDoc } from '../lib/types';
  import { highlightJson } from '../lib/utils';
  import { t, language } from '../lib/i18n';

  export let agent: AgentCard;
  export let doc: AgentDoc | undefined;

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
  <div class="modal info tall" role="dialog" aria-modal="true">
    <div class="modal-scroll">
      <div class="agent-info-header">
        <div class="role-avatar large" style={`border-color:${agent.color};background:${agent.color}22`}>
          {agent.icon}
        </div>
        <div>
          <h3>{$language === 'zh' ? agent.label : agent.label_en || agent.label}</h3>
          <p class="muted">{$language === 'zh' ? agent.desc : agent.desc_en || agent.desc}</p>
        </div>
      </div>
      {#if doc}
        <section>
          <h4>{$language === 'zh' ? '简介' : 'Introduction'}</h4>
          <p>{doc.intro}</p>
        </section>
        {#if doc.examples}
          <section>
            <h4>{$language === 'zh' ? '示例' : 'Examples'}</h4>
            <pre class="json-block">
              {@html highlightJson(doc.examples)}
            </pre>
          </section>
        {/if}
        {#if doc.interface}
          <section>
            <h4>{$language === 'zh' ? '接口定义' : 'Interface'}</h4>
            <pre class="json-block">
              {@html highlightJson(doc.interface)}
            </pre>
          </section>
        {/if}
      {:else}
        <p class="muted">{$language === 'zh' ? '暂无该智能体的文档信息。' : 'No documentation for this agent.'}</p>
      {/if}
    </div>
    <div class="modal-actions">
      <button class="ghost" on:click={() => dispatch('close')}>{$t('modal.close')}</button>
    </div>
  </div>
</div>
