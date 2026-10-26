// Hooks-only lint: rules-of-hooks and exhaustive-deps, as errors. No style rules.
import tsParser from '@typescript-eslint/parser';
import reactHooks from 'eslint-plugin-react-hooks';

export default [
  {ignores: ['node_modules/**', 'out/**', '.remotion/**']},
  {
    files: ['src/**/*.{ts,tsx}'],
    languageOptions: {parser: tsParser, parserOptions: {ecmaFeatures: {jsx: true}, sourceType: 'module'}},
    plugins: {'react-hooks': reactHooks},
    rules: {
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'error',
    },
  },
];
