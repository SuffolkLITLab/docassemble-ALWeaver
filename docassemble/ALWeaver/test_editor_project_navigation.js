'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { escapeAttribute } = require('./data/static/editor_html.js');
const source = fs.readFileSync(`${__dirname}/data/static/editor.js`, 'utf8');
const canvas = { innerHTML: '' };
const context = {
  state: {
    projects: ['default', 'One', 'Two'],
    projectSearchQuery: '',
    projectSyncs: {},
  },
  MAX_RECENT_PROJECTS: 8,
  getRecentProjectsInWorkspace: () => ['One', 'Two'],
  canvasContent: canvas,
  document: { querySelectorAll: () => [] },
  esc: escapeAttribute,
};
vm.createContext(context);
for (const name of [
  '_accordionSection',
  'getProjectCardMenuHtml',
  'renderProjectSelector',
]) {
  const start = source.indexOf(`  function ${name}(`);
  assert.ok(start >= 0);
  vm.runInContext(
    source.slice(start, source.indexOf('\n  }\n', start) + 5),
    context,
  );
}
function cards() {
  return Array.from(
    canvas.innerHTML.matchAll(/data-project-card="([^"]+)"/g),
    (m) => m[1],
  );
}
context.renderProjectSelector();
assert.deepEqual(cards(), ['default', 'One', 'Two']);
// Create from GitHub starts collapsed unless a link asked for it.
assert.match(canvas.innerHTML, /id="project-github-import-panel" class="accordion-collapse collapse"/);
context.state.openGithubImport = true;
context.renderProjectSelector();
assert.match(canvas.innerHTML, /id="project-github-import-panel" class="accordion-collapse collapse show"/);
context.state.openGithubImport = false;
assert.ok(!canvas.innerHTML.includes('Recent projects'));
assert.equal(context.getProjectCardMenuHtml('default'), '');
assert.ok(
  context
    .getProjectCardMenuHtml('One')
    .includes('data-project-action="delete"'),
);
context.state.projectSyncs.default = { branch: 'main' };
const defaultMenu = context.getProjectCardMenuHtml('default');
assert.ok(defaultMenu.includes('data-project-action="pull-github"'));
assert.ok(!defaultMenu.includes('data-project-action="delete"'));
assert.ok(!defaultMenu.includes('data-project-action="rename"'));
context.state.projects.push(
  ...Array.from({ length: 6 }, (_, n) => `Project${n}`),
);
context.renderProjectSelector();
assert.equal(cards().length, context.state.projects.length);
assert.equal(new Set(cards()).size, cards().length);
assert.ok(canvas.innerHTML.includes('Recent projects'));
assert.ok(canvas.innerHTML.includes('Other projects'));
context.state.projectSearchQuery = '  ONE ';
context.renderProjectSelector();
assert.deepEqual(cards(), ['One']);
assert.ok(!canvas.innerHTML.includes('Recent projects'));
context.state.projectSearchQuery = 'does not exist';
context.renderProjectSelector();
assert.deepEqual(cards(), []);
assert.ok(canvas.innerHTML.includes('No projects matched your search.'));
console.log('Project navigation regression tests passed');
