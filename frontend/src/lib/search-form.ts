/** Rules of one brand-check run: what is required, and how many paid searches it costs. */
import type { YandexSearchSettings } from './types';

export const MAX_PROMPTS = 20;
export const MAX_PROMPT_LENGTH = 500;
export const MAX_SEARCH_PROMPT_LENGTH = 400;
export const MAX_SEARCH_PROMPT_WORDS = 40;
export const MAX_REGIONS = 5;

export type SearchEngine = 'yandex';
export type RegionTarget = { region: number; engine: SearchEngine };

export function availableSearchEngines(settings: YandexSearchSettings | null): SearchEngine[] {
  return settings?.enabled ? ['yandex'] : [];
}

export function enabledRegionTargets(
  regions: (number | '')[],
  engines: SearchEngine[],
  available: SearchEngine[],
): RegionTarget[] {
  return regions.flatMap((region, index) => {
    const engine = engines[index] ?? 'yandex';
    return typeof region === 'number' && available.includes(engine) ? [{ region, engine }] : [];
  });
}

export type RunInput = {
  brand: string;
  domain: string;
  promptsText: string;
  providerIds: string[];
  regions: number[];
};

/** The questions of the textarea: one per line, empty lines dropped. */
export function promptsFrom(text: string): string[] {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}

/** Questions × regions: exactly how many deferred Yandex requests a run submits. */
export function requestCount(promptsText: string, regions: number[]): number {
  return promptsFrom(promptsText).length * regions.length;
}

export function requestCountLabel(count: number): string {
  const hundreds = count % 100;
  const tens = count % 10;
  let word = 'запросов';
  if (hundreds < 11 || hundreds > 14) {
    if (tens === 1) word = 'запрос';
    else if (tens >= 2 && tens <= 4) word = 'запроса';
  }
  return `${count} ${word} к Яндексу`;
}

/**
 * Returns the first problem the user has to fix, or null when the run is valid.
 *
 * A search-only run is valid: the brand belongs to the model branch, so it is
 * required only when at least one model is selected. The 400-character limit
 * applies to Yandex, the 500-character one to the models.
 */
export function validateRun(input: RunInput): string | null {
  const prompts = promptsFrom(input.promptsText);
  const searching = input.regions.length > 0;
  const checking = input.providerIds.length > 0;

  if (!searching && !checking)
    return 'Выберите хотя бы одну модель или добавьте регион для поиска в Яндексе';
  if (!prompts.length) return 'Введите хотя бы один вопрос';
  if (prompts.length > MAX_PROMPTS) return `Не больше ${MAX_PROMPTS} вопросов`;

  if (checking) {
    if (!input.brand.trim()) return 'Укажите название бренда';
    if (prompts.some((prompt) => prompt.length > MAX_PROMPT_LENGTH)) {
      return `Вопрос для проверки моделей должен быть не длиннее ${MAX_PROMPT_LENGTH} символов`;
    }
  }

  if (searching) {
    if (!input.domain.trim()) return 'Укажите сайт: без него поиск в Яндексе невозможен';
    if (input.regions.length > MAX_REGIONS) return `Не больше ${MAX_REGIONS} регионов`;
    if (new Set(input.regions).size !== input.regions.length)
      return 'Один регион можно выбрать только один раз';
    if (prompts.some((prompt) => prompt.length > MAX_SEARCH_PROMPT_LENGTH)) {
      return `Для поиска в Яндексе вопрос должен быть не длиннее ${MAX_SEARCH_PROMPT_LENGTH} символов`;
    }
    if (prompts.some((prompt) => prompt.split(/\s+/u).length > MAX_SEARCH_PROMPT_WORDS)) {
      return `Для поиска в Яндексе вопрос должен содержать не более ${MAX_SEARCH_PROMPT_WORDS} слов`;
    }
  }

  return null;
}
