import { expect, it } from 'vitest';
import { providerIcon } from './provider-icon';
it('recognizes provider names without guessing from a hosted model', () => {
  expect(providerIcon('DeepSeek · Deepseek-Flash')).toBe('deepseek-color');
  expect(providerIcon('OpenAI · GPT')).toBe('openai');
  expect(providerIcon('Custom · deepseek-chat')).toBeNull();
});
