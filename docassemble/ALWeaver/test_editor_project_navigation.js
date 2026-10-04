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

// The top-left menu offers four actual recent visits, followed by all projects.
const recentMenu = { innerHTML: '' };
const allMenu = { innerHTML: '' };
let storedRecent = ['Two', 'Gone', 'One', 'Project0', 'Project1', 'Project2'];
context.document = {
  cookie: 'playgroundproject=default',
  getElementById: (id) => ({
    'editor-recent-projects': recentMenu,
    'editor-all-projects': allMenu,
  })[id],
};
context.readRecentProjects = () => storedRecent;
for (const name of ['getCookieValue', 'getRecentProjectsInWorkspace', 'populateProjects']) {
  const start = source.indexOf(`  function ${name}(`);
  vm.runInContext(source.slice(start, source.indexOf('\n  }\n', start) + 5), context);
}
context.state.project = 'Two';
context.populateProjects();
assert.deepEqual(
  Array.from(recentMenu.innerHTML.matchAll(/data-project-card="([^"]+)"/g), (m) => m[1]),
  ['Two', 'One', 'Project0', 'Project1'],
);
assert.match(recentMenu.innerHTML, /data-project-card="Two" aria-current="true"/);
assert.equal(Array.from(allMenu.innerHTML.matchAll(/data-project-card=/g)).length, context.state.projects.length);
context.state.projects = [];
storedRecent = [];
context.populateProjects();
assert.equal(recentMenu.innerHTML, '');
assert.match(allMenu.innerHTML, /No projects yet/);

// Clicking the error count always opens the bottom drawer, including when a
// different dock was saved or the drawer was already open, without
// overwriting the saved dock.
const badgeStart = source.indexOf("    if (uiAction === 'show-errors') {");
const badgeEnd = source.indexOf('\n    // Validation drawer toggle', badgeStart);
let focused = false;
let rendered = false;
context.uiAction = 'show-errors';
context.setValidationDock = () => assert.fail('the error badge must not save a dock');
context.renderValidationDrawer = () => { rendered = true; };
context.document.getElementById = () => ({ focus: () => { focused = true; } });
for (const wasOpen of [false, true]) {
  context.state.validationOpen = wasOpen;
  context.state.validationDock = 'side';
  vm.runInContext('(function () {\n' + source.slice(badgeStart, badgeEnd) + '\n})()', context);
  assert.equal(context.state.validationOpen, true);
  assert.equal(context.state.validationDock, 'bottom');
  assert.ok(focused && rendered);
}

// Clicking the current project in the top-left menu does nothing, so unsaved
// edits survive; other projects, or the current one on the full project
// selector page, still go through the unsaved-changes check and open.
const cardStart = source.indexOf('    // Project selector cards\n    if (projectCardBtn) {');
const cardEnd = source.indexOf("\n    if (target.id === 'open-new-project-card')", cardStart);
assert.ok(cardStart >= 0 && cardEnd > cardStart);
const opened = [];
const deferred = [];
context.stashCurrentEditorState = () => true;
context.openProject = (name) => opened.push(name);
context.deferNavigationForUnsavedChanges = (reason) => {
  deferred.push(reason);
  return false;
};
function clickProjectCard(name, inMenu) {
  context.projectCardBtn = { getAttribute: () => name };
  context.target = { closest: (sel) => (inMenu && sel === '.editor-project-menu' ? {} : null) };
  vm.runInContext('(function () {\n' + source.slice(cardStart, cardEnd) + '\n})()', context);
}
context.state.project = 'One';
clickProjectCard('One', true);
assert.deepEqual(opened, []);
assert.deepEqual(deferred, []);
clickProjectCard('Two', true);
assert.deepEqual(opened, ['Two']);
assert.deepEqual(deferred, ['switch projects']);
clickProjectCard('One', false);
assert.deepEqual(opened, ['Two', 'One']);
