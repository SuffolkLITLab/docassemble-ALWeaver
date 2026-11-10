'use strict';
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(`${__dirname}/data/static/editor_reports.js`, 'utf8');
function element(tag = 'td') {
  return {tag, style: {}, children: [], appendChild(node) {this.children.push(node);}};
}
const context = {document: {createElement: element, createTextNode: text => ({textContent: text})}};
vm.createContext(context);
vm.runInContext(source, context);
const api = context.ALWeaverReports;
const cases = [
  ['Pay $10 today.', 'Pay $20 tomorrow.'],
  ['Keep ${ users[0] } exactly.', 'Please keep ${ users[0] } exactly.'],
  ['Old wording', ''], ['', 'New wording'], ['unchanged', 'unchanged'],
  ['Line one\nLine two', 'Line one\n\nLine two'], ['one  space', 'one space'],
  ['Café bientôt — sí!', 'Café demain — no!'],
  ['<img src=x onerror=alert(1)>', '<script>alert(2)</script>'],
  ['old '.repeat(10000), 'new '.repeat(10000)],
];
for (const [before, after] of cases) {
  const parts = api.wordingDiff(before, after);
  assert.strictEqual(parts.filter(p => p.type !== 'add').map(p => p.text).join(''), before);
  assert.strictEqual(parts.filter(p => p.type !== 'remove').map(p => p.text).join(''), after);
  const left = element(), right = element();
  api.fillWordingDiff(left, right, before, after);
  assert.strictEqual(left.children.map(n => n.textContent).join(''), before);
  assert.strictEqual(right.children.map(n => n.textContent).join(''), after);
  assert.ok(left.children.every(n => !n.tag || n.tag === 'del'));
  assert.ok(right.children.every(n => !n.tag || n.tag === 'ins'));
}
const parts = api.wordingDiff('Pay $10 today.', 'Pay $20 tomorrow.');
assert.strictEqual(parts.filter(p => p.type === 'remove').map(p => p.text).join('|'), '10|today');
assert.strictEqual(parts.filter(p => p.type === 'add').map(p => p.text).join('|'), '20|tomorrow');
console.log('Word-level previews preserve source text, highlight changes and render markup as text.');
