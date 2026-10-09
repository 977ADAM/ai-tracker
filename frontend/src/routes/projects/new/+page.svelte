<script lang="ts">
  import ProjectWizard from '$lib/components/ProjectWizard.svelte';
  let { data } = $props();
</script>

<svelte:head><title>Создание проекта · ИИ-трекинг</title></svelte:head>
<ProjectWizard providers={data.providers} />
