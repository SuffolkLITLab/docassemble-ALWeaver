'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(`${__dirname}/data/static/editor.js`, 'utf8');

function control() {
  const hidden = new Set(['d-none']);
  return {
    textContent: '',
    classList: {
      toggle(name, hide) { hide ? hidden.add(name) : hidden.delete(name); },
      contains(name) { return hidden.has(name); },
    },
  };
}
const controls = Object.fromEntries([
  'switch', 'home', 'playground-menu-divider', 'playground-menu-owner',
  'playground-owner-banner', 'playground-owner-label',
  'playground-selector-submit', 'playground-selector-status',
].map(name => [name, control()]));
let pendingNavigation = null;
let switched = [];
let locations = [];
const context = {
  API: '/al/editor',
  playgroundState: {enabled: true, own: false, user_id: 12, own_user_id: 7, email: '<colleague@example.org>'},
  document: {
    getElementById: id => controls[id],
    querySelectorAll: selector => selector.includes('open-playground') ? [controls.switch] : [controls.home],
  },
  getOrCreateBootstrapModal: () => ({hide() {}}),
  stashCurrentEditorState: () => true,
  deferNavigationForUnsavedChanges: (_label, continuation) => {pendingNavigation = continuation; return true;},
  apiPost: async (path, body) => {switched.push([path, body]); return {success: true};},
  window: {location: {assign: path => locations.push(path)}},
};
vm.createContext(context);
for (const name of ['renderPlaygroundContext', 'switchPlayground', 'playgroundRawUrl']) {
  const start = source.indexOf(`  function ${name}(`);
  assert.ok(start >= 0);
  vm.runInContext(source.slice(start, source.indexOf('\n  }\n', start) + 5), context);
}

(async () => {
  context.renderPlaygroundContext();
  assert.equal(controls.switch.classList.contains('d-none'), false);
  assert.equal(controls.home.classList.contains('d-none'), false);
  assert.equal(controls['playground-owner-banner'].classList.contains('d-none'), false);
  assert.equal(controls['playground-owner-label'].textContent, 'Editing the Playground of <colleague@example.org>.');
  assert.equal(context.playgroundRawUrl('/raw?filename=main.pdf'), '/raw?filename=main.pdf&playground_user_id=12');

  context.switchPlayground('7');
  assert.equal(switched.length, 0, 'Unsaved changes must resolve before selection');
  pendingNavigation();
  await Promise.resolve();
  assert.equal(switched[0][0], '/api/playground');
  assert.equal(switched[0][1].user_id, 7);
  assert.deepEqual(locations, ['/al/editor/projects']);

  context.playgroundState = {enabled: false, own: true};
  context.renderPlaygroundContext();
  for (const name of ['switch', 'home', 'playground-menu-divider', 'playground-menu-owner', 'playground-owner-banner']) {
    assert.equal(controls[name].classList.contains('d-none'), true, name);
  }
  assert.equal(context.playgroundRawUrl('/raw?filename=main.pdf'), '/raw?filename=main.pdf');

  // A failed selection leaves the existing workspace in place.
  context.apiPost = async () => {throw new Error('Sharing was disabled');};
  context.deferNavigationForUnsavedChanges = () => false;
  context.switchPlayground(12);
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(locations.length, 1);
  assert.equal(controls['playground-selector-status'].textContent, 'Sharing was disabled');
  assert.equal(controls['playground-selector-submit'].disabled, false);
  console.log('Playground selection and unsaved navigation tests passed');
})().catch(error => {console.error(error); process.exitCode = 1;});
