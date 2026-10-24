// ESLint configuration (flat config) — frontend static checks
//
// Same trade-off as backend ruff.toml: we don't chase style consistency
// (that's prettier's job), only enable rules that catch real defects,
// so hundreds of formatting warnings don't drown out genuine problems.
//
// Key rules:
//   no-unused-vars        — unused variables/imports (real defects, the pyflakes equivalent)
//   no-undef              — undefined variables (typos surface immediately)
//   vue/no-unused-refs    — refs defined but never used
//   vue/no-mutating-props — mutating props directly (Vue anti-pattern)
//   vue/require-v-for-key — v-for missing key (common root cause of broken rendering)
//   no-dupe-keys          — duplicate object keys (silent overwrite)
//   no-constant-condition — constant conditions (if (true)-style logic errors)

import js from '@eslint/js'
import tseslint from 'typescript-eslint'
import pluginVue from 'eslint-plugin-vue'
import globals from 'globals'

export default [
  {
    ignores: [
      'dist/**',
      'node_modules/**',
      'scripts/**',
      'coverage/**',
      '*.config.ts',
    ],
  },

  js.configs.recommended,
  ...tseslint.configs.recommended,
  ...pluginVue.configs['flat/recommended'],

  {
    files: ['**/*.{js,mjs,cjs,ts,mts,cts,vue}'],
    languageOptions: {
      globals: {
        ...globals.browser,
        ...globals.es2021,
      },
      parserOptions: {
        // <script lang="ts"> inside .vue files needs vue-eslint-parser + the TS parser together
        parser: tseslint.parser,
        extraFileExtensions: ['.vue'],
        sourceType: 'module',
      },
    },
    rules: {
      // Unused variables: names starting with _ are explicitly ignored
      '@typescript-eslint/no-unused-vars': [
        'error',
        {
          argsIgnorePattern: '^_',
          varsIgnorePattern: '^_',
          caughtErrorsIgnorePattern: '^_',
        },
      ],
      // These rules are too noisy for the existing codebase and unrelated to the
      // "catch real defects" goal
      'vue/multi-word-component-names': 'off',
      'vue/max-attributes-per-line': 'off',
      'vue/singleline-html-element-content-newline': 'off',
      'vue/html-self-closing': 'off',
      'vue/attributes-order': 'off',
      'vue/html-indent': 'off',
      'vue/html-closing-bracket-newline': 'off',
      'vue/first-attribute-linebreak': 'off',
      // any is unavoidable when consuming dynamic backend responses
      '@typescript-eslint/no-explicit-any': 'warn',
      // Empty functions (e.g. placeholder catch) are allowed, but deliberate
      '@typescript-eslint/no-empty-function': 'off',
    },
  },

  // Relax rules for test files
  {
    files: ['**/*.spec.ts', '**/*.test.ts'],
    languageOptions: {
      globals: {
        ...globals.node,
      },
    },
  },
]
