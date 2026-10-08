'use strict';
const assert = require('node:assert/strict');
const { makoRanges } = require('./data/static/editor_markdown.js');
function tokens(text) {
  return makoRanges(text).map((r) => text.slice(r.from, r.to));
}
assert.deepEqual(tokens('**Hello** ${ client.name }'), ['${ client.name }']);
assert.deepEqual(tokens('${ {"key": {"nested": "}"}} } tail ${ x }'), [
  '${ {"key": {"nested": "}"}} }',
  '${ x }',
]);
assert.deepEqual(tokens('% if ready:\n**yes**\n% else:\nno\n% endif'), [
  '% if ready:',
  '% else:',
  '% endif',
]);
assert.deepEqual(tokens('  % for x in items:\n${ x }\n  % endfor'), [
  '  % for x in items:',
  '${ x }',
  '  % endfor',
]);
assert.deepEqual(tokens('<%\nx = "hello"\n%>\ntext'), ['<%\nx = "hello"\n%>']);
assert.deepEqual(tokens('100% ordinary\n%% if escaped\n# Markdown'), []);
assert.deepEqual(tokens('${ incomplete'), ['${ incomplete']);
assert.deepEqual(tokens('<% incomplete'), ['<% incomplete']);
assert.deepEqual(tokens('😀 ${ "escaped \\\" }" }'), ['${ "escaped \\\" }" }']);
// Mako tags close with '>' or '/>', not '%>'.
assert.deepEqual(tokens('<%def name="greet(x)">Hi ${ x }</%def> after'), [
  '<%def name="greet(x)">',
  '${ x }',
  '</%def>',
]);
assert.deepEqual(tokens('<%include file="a > b.mako"/> tail'), [
  '<%include file="a > b.mako"/>',
]);
assert.deepEqual(tokens('<%namespace name="n" file="x"/>\n${ y }'), [
  '<%namespace name="n" file="x"/>',
  '${ y }',
]);
// <%text> content is literal: neither '${' nor '%' lines inside it are Mako.
assert.deepEqual(tokens('<%text>${ literal }\n% if no:</%text> more ${ z }'), [
  '<%text>',
  '</%text>',
  '${ z }',
]);
assert.deepEqual(tokens('<%text>${ unterminated'), ['<%text>']);
assert.deepEqual(tokens('<%def name="x()"'), ['<%def name="x()"']);
// Python blocks still end at '%>'.
assert.deepEqual(tokens('<%! import os %> and <%\nx = 1\n%>'), [
  '<%! import os %>',
  '<%\nx = 1\n%>',
]);
console.log('Markdown editor Mako range detection passed');
