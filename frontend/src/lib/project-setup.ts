import type { ProjectQuery, Competitor } from './project-types';

export function normalizeSiteInput(value: string): string {
  const text = value.trim();
  if (!text) throw new Error('Укажите сайт');
  const u = new URL(text.includes('://') ? text : 'https://' + text);
  if (!['http:', 'https:'].includes(u.protocol) || u.username || u.password)
    throw new Error('Укажите публичный сайт');
  return u.href.replace(/\/$/, '');
}
const folded = (s: string) =>
  s.normalize('NFKC').toLocaleLowerCase().replaceAll('ё', 'е').trim().replace(/\s+/g, ' ');
export function parseQueryList(text: string, existing: ProjectQuery[] = []): ProjectQuery[] {
  const lines = text
    .split(/\r?\n/)
    .map((s) => s.trim())
    .filter(Boolean);
  if (lines.length > 20) throw new Error('Добавьте не более 20 промптов');
  if (lines.some((s) => s.length > 400 || s.split(/\s+/).length > 40))
    throw new Error('Промпт: до 400 символов и 40 слов');
  if (new Set(lines.map(folded)).size !== lines.length)
    throw new Error('Промпты должны различаться');
  return lines.map((text, index) => {
    const row =
      existing.find((q) => folded(q.text) === folded(text)) ??
      (lines.length === existing.length ? existing[index] : undefined);
    return { text, category: row?.category ?? null, group: row?.group ?? null };
  });
}
export function parseCompetitorInput(value: string): Competitor {
  const text = value.trim();
  if (!text) throw new Error('Введите бренд или сайт конкурента');
  if (
    text.includes('://') ||
    (!/\s/.test(text) && /^[\p{L}\p{N}.-]+\.[\p{L}]{2,}(?:\/.*)?$/u.test(text))
  ) {
    const site_url = normalizeSiteInput(text);
    return { brand: new URL(site_url).hostname.replace(/^www\./, ''), site_url };
  }
  if (text.length > 100) throw new Error('Название конкурента: до 100 символов');
  return { brand: text, site_url: '' };
}
export async function readFileBase64(file: File): Promise<string> {
  if (file.size > 256 * 1024) throw new Error('Размер файла — до 256 КБ');
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(',')[1]);
    reader.onerror = () => reject(new Error('Не удалось прочитать файл'));
    reader.readAsDataURL(file);
  });
}
