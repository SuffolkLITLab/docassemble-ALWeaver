'use strict';
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const base = `${__dirname}/data/static/`;
let result;
const scope = {
  importScripts: (...files) => files.forEach(file => vm.runInContext(fs.readFileSync(base + file, 'utf8'), scope)),
  postMessage: data => { result = data; },
};
scope.self = scope;
vm.createContext(scope);
vm.runInContext(fs.readFileSync(base + 'editor_reports_worker.js', 'utf8'), scope);
const blocks = Array.from({length: 300}, (_, i) => ({id: `q${i}`, type: 'question', variable: `answer_${i}`, data: {question: `Screen ${i}`, yesno: `answer_${i}`}}));
const steps = blocks.map((block, i) => ({kind: 'screen', invoke: `answer_${i}`}));
scope.onmessage({data: {steps, blocks, options: {title: 'Large interview'}}});
assert.ok(!result.error, result.error);
assert.ok(result.html.includes('Large interview'));
assert.ok(result.html.includes('Screen 299'));
console.log('Large report renders without DOM globals in its worker.');
