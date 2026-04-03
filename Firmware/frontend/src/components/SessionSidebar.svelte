<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import type { AgentCard, SessionSummary } from '../lib/types';
  import { t, language } from '../lib/i18n';

  export let sessions: SessionSummary[] = [];
  export let activeSessionId: string | null = null;
  export let loading = false;
  export let agentCards: AgentCard[] = [];

  const dispatch = createEventDispatcher<{
    select: string;
    agent: AgentCard;
  }>();

</script>

<aside class="sidebar">
  <section>
    <h3>{$t('sidebar.sessions')}</h3>
    {#if loading}
      <div class="empty">{$language === 'zh' ? '加载中...' : 'Loading...'}</div>
    {:else if sessions.length === 0}
      <div class="empty">{$t('sidebar.noSessions')}</div>
    {:else}
      <ul class="session-list">
        {#each sessions as sess (sess.session_id)}
          <li class:selected={sess.session_id === activeSessionId}>
            <button
              type="button"
              class="session-entry"
              on:click={() => dispatch('select', sess.session_id)}
            >
              <div>
                <div class="session-id">{sess.label}</div>
                <small>ID: {sess.session_id.slice(0, 6)} · {$language === 'zh' ? '事件' : 'Events'}：{sess.events ?? 0}</small>
              </div>
              {#if sess.pending_audits?.length}
                <span class="badge">{sess.pending_audits.length}</span>
              {/if}
            </button>
          </li>
        {/each}
      </ul>
    {/if}
  </section>

  <section>
    <h3>{$t('sidebar.agents')}</h3>
    <div class="role-grid">
      {#each agentCards as card (card.id)}
        <button type="button" class="role-card" on:click={() => dispatch('agent', card)}>
          <div class="role-avatar" style={`border-color:${card.color};background:${card.color}22`}>
            {card.icon}
          </div>
          <div>
            <div class="role-title">{$language === 'zh' ? card.label : (card.label_en || card.label)}</div>
            <div class="role-desc">{$language === 'zh' ? card.desc : (card.desc_en || card.desc)}</div>
          </div>
        </button>
      {/each}
    </div>
  </section>
</aside>
