'use strict';
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(`${__dirname}/data/static/editor.js`, 'utf8');
let captured = 0;
let dirty = 0;
let renders = 0;
const context = {
  state: {documents: {bundles: [
    {name: 'user', elements: ['petition', 'affidavit']},
    {name: 'court', elements: ['petition']},
  ]}},
  captureDocumentEnabledInputs: () => { captured++; },
  markDocumentsDirty: () => { dirty++; },
  renderCanvas: () => { renders++; },
};
vm.createContext(context);
const start = source.indexOf('  function removeDocumentFromBundles(');
const end = source.indexOf('\n  }', start) + 4;
vm.runInContext(source.slice(start, end), context);
context.removeDocumentFromBundles('petition', 'user');
assert.deepStrictEqual(Array.from(context.state.documents.bundles[0].elements), ['affidavit']);
assert.deepStrictEqual(Array.from(context.state.documents.bundles[1].elements), ['petition']);
context.removeDocumentFromBundles('petition', null);
assert.deepStrictEqual(Array.from(context.state.documents.bundles[1].elements), []);
assert.strictEqual(captured, 2);
assert.strictEqual(dirty, 2);
assert.strictEqual(renders, 2);
context.state.documentsBusy = true;
context.removeDocumentFromBundles('affidavit', null);
assert.strictEqual(context.state.documents.bundles[0].elements.length, 1);
context.state.documentsBusy = false;
context.state.documents.documents = [{name: 'petition'}, {name: 'affidavit'}];
context.window = {confirm: () => true};
const deleteStart = source.indexOf('  function deleteDocumentFromInterview(');
vm.runInContext(source.slice(deleteStart, source.indexOf('\n  }', deleteStart) + 4), context);
context.deleteDocumentFromInterview('affidavit');
assert.deepStrictEqual(Array.from(context.state.documents.removed), ['affidavit']);
assert.strictEqual(context.state.documents.documents.length, 1);
assert.strictEqual(context.state.documents.bundles[0].elements.length, 0);
