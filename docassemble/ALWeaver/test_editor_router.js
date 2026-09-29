const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const context = { window: {} };
vm.runInNewContext(
  fs.readFileSync(path.join(__dirname, 'data/static/editor_router.js'), 'utf8'),
  context,
  { filename: 'editor_router.js' },
);
const { parseRoute, routeForState } = context.window.ALWeaverRouter;

function route(expected) {
  return {
    project: null,
    filename: null,
    blockId: null,
    view: 'interview',
    mode: 'project-selector',
    sectionFilename: null,
    ...expected,
  };
}

const cases = [
  ['/al/editor', route({})],
  ['/al/editor/', route({})],
  ['/al/editor/create', route({ mode: 'new-project' })],
  ['/al/editor/projects/P', route({ project: 'P', mode: 'question' })],
  [
    '/al/editor/projects/My%20Project/interviews/main.yml',
    route({ project: 'My Project', filename: 'main.yml', mode: 'question' }),
  ],
  [
    '/al/editor/projects/P/interviews/main.yml/blocks/q%3Aone',
    route({
      project: 'P',
      filename: 'main.yml',
      blockId: 'q:one',
      mode: 'question',
    }),
  ],
  [
    '/al/editor/projects/P/interviews/main.yml/source',
    route({ project: 'P', filename: 'main.yml', mode: 'full-yaml' }),
  ],
  [
    '/al/editor/projects/P/interviews/main.yml/order',
    route({ project: 'P', filename: 'main.yml', mode: 'order-builder' }),
  ],
  [
    '/al/editor/projects/P/interviews/main.yml/settings',
    route({
      project: 'P',
      filename: 'main.yml',
      mode: 'assemblyline-settings',
    }),
  ],
  [
    '/al/editor/projects/P/interviews/main.yml/tests',
    route({ project: 'P', filename: 'main.yml', mode: 'tests-overview' }),
  ],
  [
    '/al/editor/projects/P/interviews/main.yml/debug',
    route({ project: 'P', filename: 'main.yml', mode: 'runtime-inspector' }),
  ],
  [
    '/al/editor/projects/P/templates',
    route({ project: 'P', view: 'templates', mode: 'question' }),
  ],
  [
    '/al/editor/projects/P/modules/Foo.yml',
    route({
      project: 'P',
      view: 'modules',
      mode: 'question',
      sectionFilename: 'Foo.yml',
    }),
  ],
  [
    '/al/editor/projects/P/interviews/main.yml/documents',
    route({
      project: 'P',
      filename: 'main.yml',
      view: 'templates',
      mode: 'documents',
    }),
  ],
  [
    '/al/editor/projects/P/static/app.js',
    route({
      project: 'P',
      view: 'static',
      mode: 'question',
      sectionFilename: 'app.js',
    }),
  ],
  [
    '/al/editor/projects/P/sources/data.yml',
    route({
      project: 'P',
      view: 'data',
      mode: 'question',
      sectionFilename: 'data.yml',
    }),
  ],
  [
    '/al/editor/projects/P/documents',
    route({ project: 'P', view: 'templates', mode: 'documents' }),
  ],
];

for (const [path, expected] of cases) {
  assert.deepEqual(
    JSON.parse(JSON.stringify(parseRoute(path))),
    expected,
    path,
  );
  assert.equal(
    routeForState(expected),
    path.replace(/\/$/, '') || '/al/editor',
  );
}

const aliases = [
  ['/al/editor/projects', route({})],
  ['/al/editor/projects/', route({})],
  ['/al/editor/projects/P/interviews', route({ project: 'P', mode: 'question' })],
  ['/al/editor/projects/P/interviews/', route({ project: 'P', mode: 'question' })],
  [
    '/al/editor/projects/P/interviews/F/blocks',
    route({ project: 'P', filename: 'F', mode: 'question' }),
  ],
  [
    '/al/editor/projects/P/interviews/F/blocks/',
    route({ project: 'P', filename: 'F', mode: 'question' }),
  ],
];
for (const [path, expected] of aliases) {
  assert.deepEqual(JSON.parse(JSON.stringify(parseRoute(path))), expected, path);
  assert.notEqual(routeForState(expected), path.replace(/\/$/, ''), path);
}

for (const path of [
  '/wrong/editor',
  '/al/editor/projects/P/interviews/F/unknown',
  '/al/editor/projects/P/interviews/F/documents/extra',
  '/al/editor/projects/P/templates/a/b',
  '/al/editor/projects/P%2FQ/interviews/F',
  '/al/editor/projects/P/interviews/%2E%2E',
  '/al/editor/projects/P/interviews/F%5Cfoo',
  '/al/editor/projects/P//interviews/F',
  '/al/editor/projects/P/interviews/%ZZ',
]) {
  assert.equal(parseRoute(path), null, path);
}

assert.equal(
  routeForState(
    route({ project: 'P', filename: 'main.yml', mode: 'full-yaml' }),
  ),
  '/al/editor/projects/P/interviews/main.yml/source',
);
assert.equal(
  routeForState(route({ project: 'P', mode: 'question' })),
  '/al/editor/projects/P',
);
assert.equal(
  routeForState(
    route({
      project: 'P',
      sectionFilename: 'folder name.yml',
      view: 'data',
      mode: 'question',
    }),
  ),
  '/al/editor/projects/P/sources/folder%20name.yml',
);
assert.equal(routeForState(route({ project: '../P' })), null);
assert.equal(
  routeForState(
    route({ project: 'P', filename: 'bad/name.yml', mode: 'question' }),
  ),
  null,
);

console.log('editor_router tests passed');
