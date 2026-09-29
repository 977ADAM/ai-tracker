/**
 * Rendering of model output, which is Markdown written by an LLM and therefore
 * untrusted data: it is parsed and then always sanitized before it reaches the
 * page, so a saved answer can never inject markup or a script.
 *
 * `plainText` is the companion rule for the places that only have room for a
 * preview: the Markdown markers are stripped so a truncated fragment reads as
 * prose instead of leaking `**` and `###` into a table cell.
 */
import DOMPurify from 'dompurify';
import { marked } from 'marked';

marked.setOptions({ breaks: true, gfm: true });

/** The sanitized HTML of one Markdown fragment, ready for `{@html}`. */
export function markdownHtml(text: string): string {
  if (!text) return '';
  return DOMPurify.sanitize(marked.parse(text, { async: false }) as string);
}

/** The same text without Markdown markers, on one line, for a table preview. */
export function plainText(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/`([^`]*)`/g, '$1')
    .replace(/!\[[^\]]*\]\([^)]*\)/g, ' ')
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/^\s{0,3}#{1,6}\s*/gm, '')
    .replace(/^\s{0,3}>\s?/gm, '')
    .replace(/^\s{0,3}(?:[-*+]|\d{1,3}[.)])\s+/gm, '')
    .replace(/(\*\*|__)(.*?)\1/g, '$2')
    .replace(/(\*|_)(.*?)\1/g, '$2')
    .replace(/\s+/g, ' ')
    .trim();
}
