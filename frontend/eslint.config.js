import js from '@eslint/js';
import svelte from 'eslint-plugin-svelte';
import globals from 'globals';
import ts from 'typescript-eslint';

/** Flat config: the recommended JS, TypeScript and Svelte rules, plus Prettier compatibility. */
export default ts.config(
  js.configs.recommended,
  ...ts.configs.recommended,
  ...svelte.configs['flat/recommended'],
  ...svelte.configs['flat/prettier'],
  {
    languageOptions: {
      globals: { ...globals.browser, ...globals.node },
    },
  },
  {
    rules: {
      // Every `{@html}` of this app renders `markdownHtml` output, which is
      // sanitized with DOMPurify before it reaches the page.
      'svelte/no-at-html-tags': 'off',
      // Links point at the analysed site and at search results, which are outside
      // the app; `resolve()` only applies to the app's own routes. The two in-app
      // links use it.
      'svelte/no-navigation-without-resolve': ['error', { ignoreLinks: true }],
      // The plain collections are bookkeeping (timers, chat ids, paged traces),
      // not reactive state, so SvelteMap/SvelteSet would add noise without benefit.
      'svelte/prefer-svelte-reactivity': 'off',
    },
  },
  {
    files: ['**/*.svelte'],
    languageOptions: {
      parserOptions: { parser: ts.parser },
    },
  },
  {
    ignores: ['build/', '.svelte-kit/', 'node_modules/'],
  },
);
