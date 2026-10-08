const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(
  path.join(__dirname, 'data/static/editor.js'),
  'utf8',
);

function extractFunction(name) {
  const match = new RegExp(`(?:async\\s+)?function\\s+${name}\\s*\\(`).exec(
    source,
  );
  assert.ok(match, `could not find function ${name}`);
  const open = source.indexOf('{', match.index);
  let depth = 0;
  let quote = null;
  let lineComment = false;
  let blockComment = false;
  let escaped = false;
  for (let i = open; i < source.length; i += 1) {
    const ch = source[i];
    const next = source[i + 1];
    if (lineComment) {
      if (ch === '\n') lineComment = false;
      continue;
    }
    if (blockComment) {
      if (ch === '*' && next === '/') {
        blockComment = false;
        i += 1;
      }
      continue;
    }
    if (quote) {
      if (escaped) escaped = false;
      else if (ch === '\\') escaped = true;
      else if (ch === quote) quote = null;
      continue;
    }
    if (ch === '/' && next === '/') {
      lineComment = true;
      i += 1;
    } else if (ch === '/' && next === '*') {
      blockComment = true;
      i += 1;
    } else if (ch === '"' || ch === "'" || ch === '`') {
      quote = ch;
    } else if (ch === '{') {
      depth += 1;
    } else if (ch === '}') {
      depth -= 1;
      if (depth === 0) return source.slice(match.index, i + 1);
    }
  }
  throw new Error(`unterminated function ${name}`);
}

function testUnmappedValidationOpensFullYamlAndKeepsCrlfEdits() {
  const editedSource =
    'metadata:\r\n  title: Unsaved metadata\r\n---\r\nid: intro\r\nquestion: Unsaved question\r\n';
  const state = {
    currentView: 'interview',
    validationOpen: true,
    validationDock: 'bottom',
    canvasMode: 'full-yaml',
    fullYamlTab: 'full',
    fullYamlStash: {},
  };
  const calls = [];
  const context = vm.createContext({
    state,
    getValidationSourceSnapshot() {
      calls.push('snapshot');
      return { rawYaml: editedSource, scope: 'unsaved_source' };
    },
    dirtyState: {
      markSourceDirty(commandId) {
        calls.push(commandId);
      },
    },
    updateTopbarSaveState() {},
    window: { alert: (message) => calls.push(`alert:${message}`) },
    setValidationDock(dock) {
      state.validationDock = dock;
    },
    document: { querySelector: () => ({}) },
    setActiveTopTab() {},
    renderCanvas() {
      calls.push('canvas');
    },
    renderValidationDrawer() {
      calls.push('drawer');
    },
  });
  vm.runInContext(extractFunction('openUnmappedValidationFinding'), context);
  context.openUnmappedValidationFinding();
  assert.equal(state.canvasMode, 'full-yaml');
  assert.equal(state.fullYamlTab, 'full');
  assert.equal(state.fullYamlStash.full, editedSource);
  assert.ok(!/(^|[^\r])\n/.test(state.fullYamlStash.full));
  assert.deepEqual(calls, [
    'snapshot',
    'open-validation-source',
    'canvas',
    'drawer',
  ]);
  assert.match(state.fullYamlStash.full, /Unsaved metadata/);
  assert.match(state.fullYamlStash.full, /Unsaved question/);

  const markupStart = source.indexOf('function renderValidationDrawer');
  const markupEnd = source.indexOf(
    'function loadAssemblyLineSettings',
    markupStart,
  );
  const markup = source.slice(markupStart, markupEnd);
  assert.match(
    markup,
    /<li><button type="button" class="editor-validation-item/,
  );
  assert.match(markup, /Open full YAML: /);
  assert.match(markup, /data-source-filename=/);
  assert.match(markup, /err\.block_id && err\.line_number/);
  assert.match(source, /target\.closest\('\.editor-validation-item'\)/);
  assert.match(
    source,
    /Object\.prototype\.hasOwnProperty\.call\([\s\S]*?state\.fullYamlStash/,
  );
}

function testLateValidationResultsAreIgnoredAfterFileSwitch() {
  const context = vm.createContext({
    state: { project: 'Project', filename: 'first.yml' },
    _validationRequestSequence: 4,
  });
  vm.runInContext(extractFunction('isCurrentValidationRequest'), context);
  assert.equal(
    context.isCurrentValidationRequest(4, 'Project', 'first.yml'),
    true,
  );
  context.state.filename = 'second.yml';
  assert.equal(
    context.isCurrentValidationRequest(4, 'Project', 'first.yml'),
    false,
  );
  context.state.filename = 'first.yml';
  context._validationRequestSequence = 5;
  assert.equal(
    context.isCurrentValidationRequest(4, 'Project', 'first.yml'),
    false,
  );
}

testUnmappedValidationOpensFullYamlAndKeepsCrlfEdits();
testLateValidationResultsAreIgnoredAfterFileSwitch();
console.log('editor validation navigation tests passed');
