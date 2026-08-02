'use strict';

const assert = require('assert');
const stateApi = require('./data/static/editor_state_store.js');

function run() {
  const store = stateApi.createEditorStore({ projects: ['default'] });
  assert.deepStrictEqual(store.getState().projects, ['default']);
  assert.strictEqual(store.getState().rawYaml, '');
  assert.strictEqual(store.getState().runtimeTargetSession, null);

  const actions = [];
  const subscription = store.subscribe(function (_state, action) {
    actions.push(action.type);
  });
  store.dispatch({ type: 'merge', value: { project: 'Housing', filename: 'main.yml' } });
  assert.strictEqual(store.getState().project, 'Housing');
  assert.strictEqual(store.getState().filename, 'main.yml');
  assert.deepStrictEqual(actions, ['merge']);

  const snapshot = store.getSnapshot();
  snapshot.projects.push('mutated-copy');
  assert.deepStrictEqual(store.getState().projects, ['default']);

  store.mutateLegacy(function (state) { state.rawYaml = '---\n'; }, 'load source');
  assert.strictEqual(store.getState().rawYaml, '---\n');
  assert.deepStrictEqual(actions, ['merge', 'legacy-mutation']);
  subscription.dispose();
}

run();
