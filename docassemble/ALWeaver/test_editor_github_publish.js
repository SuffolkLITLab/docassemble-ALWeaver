'use strict';

const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const source = fs.readFileSync(`${__dirname}/data/static/editor.js`, 'utf8');
function element() {
  const classes = new Set(['d-none']);
  return {
    value: '',
    options: [],
    classList: {
      add: (name) => classes.add(name),
      remove: (name) => classes.delete(name),
      contains: (name) => classes.has(name),
      toggle(name, force) {
        if (force) classes.add(name);
        else classes.delete(name);
      },
    },
    replaceChildren() {
      this.options = [];
    },
    appendChild(option) {
      this.options.push(option);
    },
    prepend(option) {
      this.options.unshift(option);
    },
    removeAttribute(name) {
      delete this[name];
    },
  };
}

const ids = [
  'github-publish-status',
  'github-publish-existing',
  'github-repository-link',
  'github-commit-link',
  'github-publish-submit',
  'github-publish-preview-button',
  'github-configure-link',
  'github-package-name',
  'github-branch-name',
  'github-owner',
];
const elements = Object.fromEntries(ids.map((id) => [id, element()]));
const context = {
  document: {
    getElementById: (id) => elements[id],
    createElement: () => element(),
  },
  githubWorkflowAccessByOwner: {},
  showGithubWorkflowAccess() {},
};
vm.createContext(context);
for (const name of [
  'setGithubPublishStatus',
  'showGithubPublishedTarget',
  'applyGithubIntegrationStatus',
]) {
  const start = source.indexOf(`  function ${name}(`);
  assert.ok(start >= 0, name);
  vm.runInContext(
    source.slice(start, source.indexOf('\n  }\n', start) + 5),
    context,
  );
}

const commit = 'a'.repeat(40);
const repositoryUrl = 'https://github.com/LegalAid/docassemble-HousingForms';
const sync = {
  package: 'HousingForms',
  owner: 'LegalAid',
  repository_url: repositoryUrl,
  branch: 'feature/housing',
  published: true,
  commit_url: `${repositoryUrl}/commit/${commit}`,
};
const connected = {
  enabled: true,
  connected: true,
  default_package: 'NewProject',
  owners: [
    { login: 'ada', type: 'user' },
    { login: 'LegalAid', type: 'organization' },
  ],
};
context.applyGithubIntegrationStatus({ ...connected, sync });
assert.strictEqual(elements['github-package-name'].value, 'HousingForms');
assert.strictEqual(elements['github-branch-name'].value, 'feature/housing');
assert.strictEqual(elements['github-owner'].value, 'LegalAid');
assert.strictEqual(elements['github-repository-link'].href, repositoryUrl);
assert.strictEqual(elements['github-commit-link'].href, sync.commit_url);
assert.ok(!elements['github-publish-existing'].classList.contains('d-none'));
assert.ok(elements['github-publish-existing'].textContent.includes('Last published'));

context.applyGithubIntegrationStatus({ ...connected, sync: null });
assert.strictEqual(elements['github-package-name'].value, 'NewProject');
assert.strictEqual(elements['github-branch-name'].value, 'main');
assert.ok(elements['github-publish-existing'].classList.contains('d-none'));
assert.ok(elements['github-repository-link'].classList.contains('d-none'));
assert.strictEqual(elements['github-repository-link'].href, undefined);

context.applyGithubIntegrationStatus({
  ...connected,
  sync: { ...sync, published: false, commit_url: null },
});
assert.strictEqual(elements['github-package-name'].value, 'HousingForms');
assert.strictEqual(elements['github-branch-name'].value, 'feature/housing');
assert.ok(elements['github-publish-existing'].classList.contains('d-none'));
assert.ok(elements['github-commit-link'].classList.contains('d-none'));

context.applyGithubIntegrationStatus({
  ...connected,
  owners: [{ login: 'ada', type: 'user' }],
  sync,
});
assert.strictEqual(elements['github-owner'].value, '');
assert.strictEqual(elements['github-owner'].options[0].value, '');
assert.ok(elements['github-publish-status'].textContent.includes('unavailable'));
assert.ok(!elements['github-publish-existing'].classList.contains('d-none'));

context.applyGithubIntegrationStatus({
  enabled: false,
  connected: false,
  sync,
});
assert.strictEqual(elements['github-repository-link'].href, repositoryUrl);
assert.ok(!elements['github-publish-existing'].classList.contains('d-none'));
