import js from '@eslint/js'
import globals from 'globals'
import tseslint from 'typescript-eslint'
import { globalIgnores } from 'eslint/config'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'

// eslint-plugin-react-hooks v7 ships an eslintrc-style config under
// `recommended-latest` (plugins: string[]). Flatten to a plain rules map so
// ESLint 9 flat config accepts it.
function flatRules(hooksConfig) {
  if (!hooksConfig) return {}
  const rules = { ...(hooksConfig.rules || {}) }
  return rules
}

export default tseslint.config([
  globalIgnores(['dist', 'node_modules', 'src/sdk/types.gen.ts']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [js.configs.recommended, tseslint.configs.recommended],
    languageOptions: {
      ecmaVersion: 2020,
      globals: { ...globals.browser, ...globals.node },
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...flatRules(reactHooks.configs && reactHooks.configs['recommended-latest']),
      // Data-loading effects (fetch + setState) are the standard pattern for
      // this app's server-driven pages; the v7 `set-state-in-effect` rule is
      // aimed at state-derivation effects, not data fetching. Same for
      // `immutability` (function hoisting in components).
      'react-hooks/set-state-in-effect': 'off',
      'react-hooks/immutability': 'off',
      ...reactRefresh.configs.vite.rules,
      '@typescript-eslint/no-explicit-any': 'warn',
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
    },
  },
])
