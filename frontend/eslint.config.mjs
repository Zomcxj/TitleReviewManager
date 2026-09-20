// ESLint 配置（flat config）—— 前端静态检查
//
// 与后端 ruff.toml 同样的取舍：不追求风格统一（那是 prettier 的事），
// 只启用能发现真实缺陷的规则，避免几百条格式告警淹没真问题。
//
// 重点规则：
//   no-unused-vars        —— 未使用变量/导入（真缺陷，也是 pyflakes 的等价物）
//   no-undef              —— 未定义变量（打字错误会立刻暴露）
//   vue/no-unused-refs    —— 定义了但没用到的 ref
//   vue/no-mutating-props —— 直接改 props（Vue 反模式）
//   vue/require-v-for-key —— v-for 缺 key（渲染错乱的常见根因）
//   no-dupe-keys          —— 对象重复键（静默覆盖）
//   no-constant-condition —— 恒定条件（if (true) 类逻辑错误）

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
        // .vue 文件里的 <script lang="ts"> 需要 vue-eslint-parser + ts 解析器组合
        parser: tseslint.parser,
        extraFileExtensions: ['.vue'],
        sourceType: 'module',
      },
    },
    rules: {
      // 未使用变量：允许以 _ 开头显式忽略
      '@typescript-eslint/no-unused-vars': [
        'error',
        {
          argsIgnorePattern: '^_',
          varsIgnorePattern: '^_',
          caughtErrorsIgnorePattern: '^_',
        },
      ],
      // 以下规则对现有代码噪音过大，且与「发现真缺陷」的目标无关
      'vue/multi-word-component-names': 'off',
      'vue/max-attributes-per-line': 'off',
      'vue/singleline-html-element-content-newline': 'off',
      'vue/html-self-closing': 'off',
      'vue/attributes-order': 'off',
      'vue/html-indent': 'off',
      'vue/html-closing-bracket-newline': 'off',
      'vue/first-attribute-linebreak': 'off',
      // any 在对接后端动态响应时无法完全避免
      '@typescript-eslint/no-explicit-any': 'warn',
      // 空函数（如占位 catch）允许，但要显式
      '@typescript-eslint/no-empty-function': 'off',
    },
  },

  // 测试文件放宽
  {
    files: ['**/*.spec.ts', '**/*.test.ts'],
    languageOptions: {
      globals: {
        ...globals.node,
      },
    },
  },
]
