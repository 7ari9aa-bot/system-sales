import js from '@eslint/js'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import globals from 'globals'
import tseslint from 'typescript-eslint'

const BANNED_GLOBALS = ['fetch', 'XMLHttpRequest', 'EventSource', 'localStorage', 'sessionStorage'].map(
  (name) => ({
    name,
    message:
      'The React tree talks to the outside world only through src/platform. See desktop/docs/platform-boundary.md.',
  }),
)

const BANNED_SYNTAX = [
  {
    selector: "CallExpression[callee.name='invoke']",
    message: 'invoke() belongs in src/platform/tauri/ — the UI must not know a Tauri runtime exists.',
  },
  {
    selector: "CallExpression[callee.name='fetch']",
    message: 'Network calls belong behind the platform transport (src/platform/tauri).',
  },
  {
    selector: "NewExpression[callee.name='EventSource']",
    message: 'SSE belongs to the platform event plane; the webview EventSource cannot send an auth header.',
  },
]

export default tseslint.config(
  {
    // The boundary fixtures are deliberately illegal source — linting them would
    // fail on purpose-built samples, and the scanner's own tests cover them.
    ignores: [
      'dist/**',
      'node_modules/**',
      'coverage/**',
      'src-tauri/target/**',
      'src-tauri/gen/**',
      'config/__fixtures__/**',
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['src/**/*.{ts,tsx}'],
    languageOptions: {
      globals: globals.browser,
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    extends: [tseslint.configs.recommendedTypeChecked],
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': ['error', { allowConstantExport: true }],
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_', caughtErrorsIgnorePattern: '^_' },
      ],
      'no-restricted-globals': ['error', ...BANNED_GLOBALS],
      'no-restricted-syntax': ['error', ...BANNED_SYNTAX],
    },
  },
  {
    // The adapter directory is the one place that may reach the runtime.
    files: ['src/platform/tauri/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-imports': 'off',
      'no-restricted-globals': 'off',
      'no-restricted-syntax': 'off',
    },
  },
  {
    // Tests and node-side gate scripts keep Node globals and may use fetch-free
    // helpers freely; the bans above are for application code. Tests also read
    // untyped JSON out of src-tauri/*.json, which needs a foothold in `any` the
    // production code is not allowed to take.
    files: ['src/**/*.test.{ts,tsx}', 'src/test/**/*.{ts,tsx}', 'config/**/*.{mjs,js}'],
    languageOptions: { globals: { ...globals.browser, ...globals.node } },
    rules: {
      'no-restricted-syntax': 'off',
      '@typescript-eslint/no-explicit-any': 'off',
      '@typescript-eslint/consistent-type-assertions': 'off',
      // A test that reads tauri.conf.json is reading untyped JSON by definition.
      '@typescript-eslint/no-unsafe-member-access': 'off',
      '@typescript-eslint/no-unsafe-assignment': 'off',
      '@typescript-eslint/no-unsafe-return': 'off',
      // One test throws a bare string precisely to prove the boundary survives a
      // value that is not an Error; the rule is right about production code.
      '@typescript-eslint/only-throw-error': 'off',
    },
  },
  {
    files: ['*.ts', 'config/**/*.mjs'],
    languageOptions: { globals: globals.node },
    rules: {
      'no-restricted-syntax': 'off',
      'no-restricted-globals': 'off',
    },
  },
)
