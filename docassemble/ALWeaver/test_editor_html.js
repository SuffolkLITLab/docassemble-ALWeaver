'use strict';

const assert = require('assert');
const html = require('./data/static/editor_html.js');

assert.strictEqual(html.escapeAttribute(null), '');
assert.strictEqual(html.escapeAttribute(undefined), '');
assert.strictEqual(html.escapeAttribute('plain text'), 'plain text');
assert.strictEqual(
  html.escapeAttribute(`A & B < C > D "quoted" and 'single'`),
  'A &amp; B &lt; C &gt; D &quot;quoted&quot; and &#39;single&#39;'
);
assert.strictEqual(html.escapeAttribute(42), '42');
