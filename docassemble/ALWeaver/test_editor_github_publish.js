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
  'github-new-branch-name',
  'github-branch-retry',
  'github-owner',
];
const elements = Object.fromEntries(ids.map((id) => [id, element()]));
let branches = ['main', 'feature/housing'];
const context = {
  document: {
    getElementById: (id) => elements[id],
    createElement: () => element(),
  },
  githubWorkflowAccessByOwner: {},
  state: { project: 'Housing' },
  apiGet: async () => ({
    success: true,
    data: { branches, default_branch: 'main' },
  }),
  showGithubWorkflowAccess() {},
  clearTimeout,
};
vm.createContext(context);
context.githubBranchRequest = 0;
context.githubBranchTimer = null;
context.githubPublishBlocked = false;
context.githubPreviewInFlight = false;
context.githubPublishInFlight = false;
for (const name of [
  'updateGithubPublishSubmit',
  'setGithubPublishStatus',
  'showGithubPublishedTarget',
  'githubBranchValue',
  'updateGithubNewBranchInput',
  'resetGithubBranchChoices',
  'loadGithubBranches',
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
async function run() {
context.applyGithubIntegrationStatus({ ...connected, sync });
await Promise.resolve();
assert.strictEqual(elements['github-package-name'].value, 'HousingForms');
assert.strictEqual(elements['github-branch-name'].value, 'feature/housing');
assert.deepStrictEqual(
  elements['github-branch-name'].options.map((option) => option.value),
  ['main', 'feature/housing', '<new>'],
);
assert.strictEqual(elements['github-branch-name'].options.at(-1).textContent, 'New branch...');
assert.ok(elements['github-new-branch-name'].disabled);
assert.strictEqual(elements['github-owner'].value, 'LegalAid');
assert.strictEqual(elements['github-repository-link'].href, repositoryUrl);
assert.strictEqual(elements['github-commit-link'].href, sync.commit_url);
assert.ok(!elements['github-publish-existing'].classList.contains('d-none'));
assert.ok(elements['github-publish-existing'].textContent.includes('Last published'));
// Publishing does not wait for a preview once the target branch is loaded.
assert.strictEqual(elements['github-publish-submit'].disabled, false);
assert.strictEqual(elements['github-publish-preview-button'].disabled, false);

context.applyGithubIntegrationStatus({ ...connected, sync: null });
await Promise.resolve();
assert.strictEqual(elements['github-package-name'].value, 'NewProject');
assert.strictEqual(elements['github-branch-name'].value, 'main');
assert.ok(elements['github-publish-existing'].classList.contains('d-none'));
assert.ok(elements['github-repository-link'].classList.contains('d-none'));
assert.strictEqual(elements['github-repository-link'].href, undefined);

context.applyGithubIntegrationStatus({
  ...connected,
  sync: { ...sync, published: false, commit_url: null },
});
await Promise.resolve();
assert.strictEqual(elements['github-package-name'].value, 'HousingForms');
assert.strictEqual(elements['github-branch-name'].value, 'feature/housing');
assert.ok(elements['github-publish-existing'].classList.contains('d-none'));
assert.ok(elements['github-commit-link'].classList.contains('d-none'));

branches = ['main'];
context.applyGithubIntegrationStatus({ ...connected, sync });
await Promise.resolve();
assert.strictEqual(elements['github-branch-name'].value, '<new>');
assert.strictEqual(elements['github-new-branch-name'].value, 'feature/housing');
assert.ok(elements['github-new-branch-name'].required);
assert.strictEqual(context.githubBranchValue(), 'feature/housing');
elements['github-branch-name'].value = 'main';
context.updateGithubNewBranchInput();
assert.ok(elements['github-new-branch-name'].disabled);
assert.strictEqual(context.githubBranchValue(), 'main');

branches = [];
context.applyGithubIntegrationStatus({ ...connected, sync: null });
await Promise.resolve();
assert.strictEqual(elements['github-branch-name'].value, '<new>');
assert.strictEqual(elements['github-new-branch-name'].value, 'main');

context.apiGet = async () => ({
  success: false,
  error: { message: 'GitHub is temporarily unavailable.' },
});
context.loadGithubBranches();
await Promise.resolve();
await Promise.resolve();
assert.ok(elements['github-branch-name'].disabled);
assert.ok(!elements['github-branch-retry'].classList.contains('d-none'));
assert.ok(elements['github-publish-status'].textContent.includes('temporarily unavailable'));

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
}

run().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
