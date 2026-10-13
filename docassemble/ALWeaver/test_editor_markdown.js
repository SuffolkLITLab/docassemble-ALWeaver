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
assert.deepEqual(tokens('${ incomplete'), ['${']);
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
assert.deepEqual(tokens('<%answer = 2 > 1%> tail ${ answer }'), [
  '<%answer = 2 > 1%>',
  '${ answer }',
]);
assert.deepEqual(tokens('<%text_value = 2 > 1%>'), ['<%text_value = 2 > 1%>']);
assert.deepEqual(tokens('<%answer = 2 >'), ['<%answer = 2 >']);
// Python blocks still end at '%>'.
assert.deepEqual(tokens('<%! import os %> and <%\nx = 1\n%>'), [
  '<%! import os %>',
  '<%\nx = 1\n%>',
]);
console.log('Markdown editor Mako range detection passed');

function expression(text, index = 0) {
  const token = makoRanges(text)[index];
  return token.editable
    ? text.slice(token.expressionFrom, token.expressionTo)
    : null;
}
assert.deepEqual(tokens('😀 ${ x }${ x }'), ['${ x }', '${ x }']);
assert.equal(makoRanges('😀 ${ x }')[0].from, 3);
assert.equal(
  expression('${ currency(monthly_income) }'),
  'currency(monthly_income)',
);
assert.equal(
  expression('${ {"a": ["}", {"b": 2}]} }'),
  '{"a": ["}", {"b": 2}]}',
);
assert.equal(expression('${ (\n  x + y\n) }'), '(\n  x + y\n)');
assert.equal(expression('${ """a } b""" }'), '"""a } b"""');
assert.equal(expression('${ (x # } comment\n) }'), '(x # } comment\n)');
assert.equal(expression('${ value | h }'), null);
assert.equal(expression('${ value | trim, h }'), null);
assert.equal(expression('${ (a | b) }'), '(a | b)');
assert.equal(expression('${ "|" }'), '"|"');
assert.equal(expression('${ [x for x in items] }'), '[x for x in items]');
assert.equal(expression('${ }'), '');
assert.deepEqual(tokens('  ## ${ ignored }\n${ live }'), ['${ live }']);
assert.deepEqual(tokens('<%doc>${ hidden }\n% if no:\n</%doc>${ live }'), [
  '${ live }',
]);
assert.deepEqual(tokens('<%doc>${ incomplete'), []);
assert.deepEqual(tokens('${ (broken } prose ${ next }'), ['${', '${ next }']);
assert.deepEqual(tokens('${ unclosed ${ next }'), ['${', '${ next }']);
assert.equal(expression('${ "unclosed }'), null);
assert.equal(expression('% if ready:'), null);
assert.equal(expression('<% x = 2 %>'), null);
assert.deepEqual(tokens('<% doc = 1 %>\n${ live }'), [
  '<% doc = 1 %>',
  '${ live }',
]);
assert.deepEqual(tokens('<% text = "a" %>\n${ live }'), [
  '<% text = "a" %>',
  '${ live }',
]);
assert.deepEqual(tokens('<%text>${ lit }</%text > ${ live }'), [
  '<%text>',
  '</%text >',
  '${ live }',
]);
assert.deepEqual(tokens('% def hello(name):\nHello ${ name }\n% enddef'), [
  '% def hello(name):',
  '${ name }',
  '% enddef',
]);
