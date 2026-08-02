'use strict';

const assert = require('assert');
const api = require('./data/static/editor_api_client.js');

function jsonResponse(payload, status) {
  return new Response(JSON.stringify(payload), {
    status: status || 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

async function expectError(promise, expected) {
  try {
    await promise;
    assert.fail('Expected EditorApiError');
  } catch (error) {
    assert.ok(error instanceof api.EditorApiError, error);
    Object.keys(expected).forEach((key) => assert.strictEqual(error[key], expected[key], key));
  }
}

async function run() {
  const requests = [];
  const client = api.createClient({
    baseUrl: '/al/editor',
    csrfToken: 'csrf-value',
    fetchImpl: async (url, options) => {
      requests.push({ url, options });
      return jsonResponse({ success: true, data: { raw_yaml: '' } });
    },
    requestIdFactory: () => 'request-123',
  });
  const payload = await client.post('/api/file', { content: '' });
  assert.strictEqual(payload.data.raw_yaml, '');
  assert.strictEqual(requests[0].options.headers['X-CSRF-Token'], 'csrf-value');
  assert.strictEqual(requests[0].options.headers['X-Request-ID'], 'request-123');
  assert.strictEqual(requests[0].options.credentials, 'same-origin');

  const uploadRequests = [];
  const uploadClient = api.createClient({
    csrfToken: 'upload-csrf',
    fetchImpl: async (url, options) => {
      uploadRequests.push({ url, options });
      return jsonResponse({ success: true, data: { saved_files: ['brief.pdf'] } });
    },
  });
  const formData = new FormData();
  formData.append('files', new Blob(['contents']), 'brief.pdf');
  await uploadClient.upload('/api/upload', formData);
  assert.strictEqual(uploadRequests[0].options.body, formData);
  assert.strictEqual(uploadRequests[0].options.headers['X-CSRF-Token'], 'upload-csrf');
  assert.strictEqual(uploadRequests[0].options.headers['Content-Type'], undefined);

  const httpClient = api.createClient({
    fetchImpl: async () => jsonResponse({
      error: { code: 'revision_conflict', message: 'Changed', details: { current: 'b' } },
    }, 409),
  });
  await expectError(httpClient.get('/conflict'), {
    status: 409,
    code: 'revision_conflict',
    message: 'Changed',
  });

  const htmlClient = api.createClient({
    fetchImpl: async () => new Response('<html>Error</html>', {
      status: 500,
      headers: { 'Content-Type': 'text/html' },
    }),
  });
  await expectError(htmlClient.get('/html'), { status: 500, code: 'invalid_content_type' });

  const malformedClient = api.createClient({
    fetchImpl: async () => new Response('{', {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  });
  await expectError(malformedClient.get('/bad-json'), { status: 200, code: 'invalid_json' });

  const synchronousFailureClient = api.createClient({
    fetchImpl: () => { throw new Error('socket unavailable'); },
  });
  await expectError(synchronousFailureClient.get('/sync-failure'), { code: 'network_error' });

  let resolveFirst;
  const staleClient = api.createClient({
    fetchImpl: (url) => {
      if (url.includes('first')) {
        return new Promise((resolve) => { resolveFirst = resolve; });
      }
      return Promise.resolve(jsonResponse({ success: true, data: { value: 'new' } }));
    },
  });
  const first = staleClient.get('/api/file?name=first');
  const second = staleClient.get('/api/file?name=second');
  assert.strictEqual((await second).data.value, 'new');
  resolveFirst(jsonResponse({ success: true, data: { value: 'old' } }));
  await expectError(first, { code: 'stale_response' });

  const writeResolvers = [];
  const writeClient = api.createClient({
    fetchImpl: () => new Promise((resolve) => { writeResolvers.push(resolve); }),
  });
  const firstWrite = writeClient.post('/api/file', { raw_yaml: 'first' });
  const secondWrite = writeClient.post('/api/file', { raw_yaml: 'second' });
  await Promise.resolve();
  writeResolvers[1](jsonResponse({ success: true, data: { revision: 'second' } }));
  writeResolvers[0](jsonResponse({ success: true, data: { revision: 'first' } }));
  assert.strictEqual((await firstWrite).data.revision, 'first');
  assert.strictEqual((await secondWrite).data.revision, 'second');
}

run().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
