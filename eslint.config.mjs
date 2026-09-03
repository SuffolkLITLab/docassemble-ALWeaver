import js from '@eslint/js';
import globals from 'globals';
import sonarjs from 'eslint-plugin-sonarjs';

const endpointFiles = [
  'docassemble/ALWeaver/data/static/editor_api_client.js',
  'docassemble/ALWeaver/data/static/editor_agent_chat.js',
  'docassemble/ALWeaver/data/static/editor_module_restart.js',
  'docassemble/ALWeaver/data/static/editor_runtime_inspector.js',
  'docassemble/ALWeaver/data/static/editor_validation_source.js',
  'docassemble/ALWeaver/data/static/editor_dirty_state.js',
  'docassemble/ALWeaver/data/static/editor_html.js',
];

export default [
  {
    ignores: ['node_modules/**'],
  },
  {
    files: endpointFiles,
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'script',
      globals: {
        ...globals.browser,
        ...globals.node,
      },
    },
    plugins: {
      sonarjs,
    },
    rules: {
      ...js.configs.recommended.rules,
      ...sonarjs.configs.recommended.rules,
      // These browser modules intentionally use nested closures for their
      // stateful controllers and promise callbacks. Keep the other SonarJS
      // correctness rules active without penalising that implementation shape.
      'sonarjs/no-nested-functions': 'off',
      'sonarjs/cognitive-complexity': 'off',
    },
  },
];
