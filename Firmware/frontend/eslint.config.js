import svelte from 'eslint-plugin-svelte';
import tsParser from '@typescript-eslint/parser';

export default [
  {
    ignores: ['dist', 'node_modules'],
  },
  {
    files: ['src/**/*.{ts,js}'],
    languageOptions: {
      parser: tsParser,
      parserOptions: {
        sourceType: 'module',
        ecmaVersion: 'latest',
      },
    },
  },
  ...svelte.configs['flat/recommended'].map((config) => ({
    ...config,
    languageOptions: {
      ...(config.languageOptions ?? {}),
      parserOptions: {
        ...(config.languageOptions?.parserOptions ?? {}),
        // Feed TypeScript into the Svelte parser for <script lang="ts"> blocks.
        parser: tsParser,
      },
    },
  })),
  {
    files: ['src/**/*.{ts,js,svelte}'],
    languageOptions: {
      parserOptions: {
        // We rely on TS inside Svelte files; no project-level type checking here.
        project: false,
      },
    },
    rules: {
      // We intentionally render trusted Markdown; guard at data layer rather than blocking {@html}.
      'svelte/no-at-html-tags': 'off',
    },
  },
];
