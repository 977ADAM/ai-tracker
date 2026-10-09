<script lang="ts">
  import ProjectWizard from '$lib/components/ProjectWizard.svelte';
  let { data } = $props();
</script>

<svelte:head><title>Настройка проекта · ИИ-трекинг</title></svelte:head>
<ProjectWizard initial={data.project} providers={data.providers} />
