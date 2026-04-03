<script lang="ts">
  import { createEventDispatcher } from 'svelte';

  export let logs = '';
  const dispatch = createEventDispatcher<{ close: void }>();
</script>

<div
  class="modal-backdrop"
  role="presentation"
  tabindex="-1"
  on:click={(event) => {
    if (event.target === event.currentTarget) dispatch('close');
  }}
  on:keydown={(event) => {
    if (event.key === 'Escape') dispatch('close');
  }}
>
  <div class="modal log" role="dialog" aria-modal="true">
    <h3>最新日志</h3>
    <pre>{logs}</pre>
    <button class="ghost" on:click={() => dispatch('close')}>关闭</button>
  </div>
</div>
