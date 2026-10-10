/** Match explicit provider names only; custom connections keep their initials. */
export function providerIcon(name: string): string | null {
  const provider = name.split(' · ')[0].trim().toLowerCase();
  const icons: Record<string, string> = {
    deepseek: 'deepseek-color',
    openai: 'openai',
    chatgpt: 'openai',
    anthropic: 'claude-color',
    claude: 'claude-color',
    google: 'gemini-color',
    gemini: 'gemini-color',
    perplexity: 'perplexity-color',
    xai: 'grok',
    grok: 'grok',
    mistral: 'mistral-color',
    qwen: 'qwen-color',
  };
  return icons[provider] ?? null;
}
