'use strict';

const assert = require('assert');
const { createModuleRestartController } = require('./data/static/editor_module_restart.js');

function makeController(policy, restartAllowed = true) {
  const calls = { state: 0, restart: 0, status: 0 };
  const api = {
    get: async (path) => {
      if (path.startsWith('/api/server/restart-state')) {
        calls.state += 1;
        return {
          data: {
            pending: true,
            files: [{ filename: 'matrix_pkg02_helper.py', reason: 'changed' }],
            policy,
            restart_allowed: restartAllowed,
            restart_blocked_reason: 'Restart disabled in this test.',
          },
        };
      }
      calls.status += 1;
      return { data: { status: 'completed' } };
    },
    post: async () => {
      calls.restart += 1;
      return { data: { task_id: 'synthetic-restart' } };
    },
  };
  return {
    calls,
    controller: createModuleRestartController({
      api,
      document: null,
      window: { setTimeout: (callback) => callback() },
      getProject: () => 'matrix_pkg02',
      sleep: async () => {},
      now: () => 0,
    }),
  };
}

(async () => {
  const never = makeController('never');
  assert.strictEqual(await never.controller.ensureModulesLoaded('run'), true);
  assert.strictEqual(never.calls.restart, 0, 'never policy must not restart');
  assert.strictEqual(never.calls.state, 1);

  const auto = makeController('auto');
  assert.strictEqual(await auto.controller.ensureModulesLoaded('run'), true);
  assert.strictEqual(auto.calls.restart, 1, 'auto policy restarts before run');
  assert.strictEqual(auto.calls.status, 1, 'auto waits for restart completion');
  assert.strictEqual(auto.controller.currentState(), null);

  const autoBlocked = makeController('auto', false);
  assert.strictEqual(
    await autoBlocked.controller.ensureModulesLoaded('run'),
    true,
  );
  assert.strictEqual(
    autoBlocked.calls.restart,
    0,
    'auto policy cannot invoke a restart when the server disallows it',
  );

  // In a headless shell without the modal, prompt mode must fail open for the
  // pending action without silently starting a server-wide restart.
  const prompt = makeController('prompt');
  assert.strictEqual(await prompt.controller.ensureModulesLoaded('run'), true);
  assert.strictEqual(prompt.calls.restart, 0);
  console.log('module restart policy checks passed');
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
