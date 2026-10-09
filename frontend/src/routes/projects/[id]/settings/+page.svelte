<script lang="ts">
  import ProjectForm from '$lib/components/ProjectForm.svelte';
  let { data } = $props();
</script>

<svelte:head><title>Настройки проекта · ИИ-трекинг</title></svelte:head>
<main class="mx-auto max-w-4xl px-4 py-8 sm:px-6">
  <a href={`/projects/${data.project.id}`} class="text-sm text-muted">← {data.project.name}</a>
  <h1 class="mt-4 mb-6 text-3xl font-semibold">Настройки проекта</h1>
  <ProjectForm initial={data.project} providers={data.providers} />
</main>
