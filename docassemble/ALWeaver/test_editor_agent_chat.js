'use strict';

/* Chat-panel behaviour: session lifecycle, apply gating and stale handling.
 *
 * A small DOM shim stands in for the browser so the panel's render path runs
 * for real; asserting on the rendered tree is what keeps Apply from being
 * offered for a candidate the server refused. */

const assert = require('assert');

function createNode(tag) {
  const node = {
    tagName: tag,
    className: '',
    textContent: '',
    children: [],
    listeners: {},
    attributes: {},
    scrollTop: 0,
    scrollHeight: 0,
    appendChild(child) {
      this.children.push(child);
      return child;
    },
    addEventListener(name, handler) {
      this.listeners[name] = handler;
    },
    setAttribute(name, value) {
      this.attributes[name] = value;
    },
    classList: {
      toggle(name, on) {
        this._on = this._on || {};
        this._on[name] = Boolean(on);
      },
    },
    querySelector(selector) {
      const wanted = String(selector).replace(/^\./, '');
      let found = null;
      walk(this, (node) => {
        if (!found && String(node.className).split(' ').indexOf(wanted) !== -1) found = node;
      });
      return found;
    },
  };
  Object.defineProperty(node, 'innerHTML', {
    set(value) {
      if (!value) this.children = [];
    },
    get() {
      return '';
    },
  });
  return node;
}

global.document = {
  createElement: createNode,
};

const chatModule = require('./data/static/editor_agent_chat.js');

function walk(node, visit) {
  visit(node);
  (node.children || []).forEach((child) => walk(child, visit));
}

function findAll(root, predicate) {
  const found = [];
  walk(root, (node) => {
    if (predicate(node)) found.push(node);
  });
  return found;
}

function buttonNamed(root, text) {
  return findAll(root, (node) => node.tagName === 'button' && node.textContent === text)[0];
}

function createHarness(options) {
  options = options || {};
  const calls = [];
  const responses = options.responses || {};
  const api = {
    post(path, body, requestOptions) {
      calls.push({ method: 'POST', path, body, requestOptions });
      const responder = responses[path];
      if (!responder) return Promise.resolve({ success: true, data: {} });
      const value = typeof responder === 'function' ? responder(body) : responder;
      return value instanceof Error ? Promise.reject(value) : Promise.resolve(value);
    },
    delete(path) {
      calls.push({ method: 'DELETE', path });
      return Promise.resolve({ success: true, data: {} });
    },
    get(path, requestOptions) {
      calls.push({ method: 'GET', path, requestOptions });
      const responder = responses[path];
      if (!responder) return Promise.resolve({ success: true, data: {} });
      const value = typeof responder === 'function' ? responder() : responder;
      return value instanceof Error ? Promise.reject(value) : Promise.resolve(value);
    },
  };
  const applied = [];
  const chat = chatModule.createAgentChat({
    api,
    getContext: () => ({ project: 'default', filename: 'main.yml', selectedBlockId: 'intro' }),
    getAvailability: () => options.availability ||
      { available: true, code: 'ready', message: '' },
    getWorkingSource: options.getWorkingSource || (() => ({
      raw_yaml: 'id: intro\nquestion: Hi\n',
      base_revision: 'saved-revision',
      has_unsaved_changes: true,
      source_scope: 'working_source',
    })),
    onApply: (data) => applied.push(data),
  });
  const container = createNode('div');
  chat.render(container);
  return { chat, container, calls, applied };
}

const TURN_STARTED = { success: true, data: { started: true } };

// The POST only starts the work; this is what the browser polls for.
function finishedProgress(result) {
  return { success: true, data: { running: false, started_at: 0, events: [], result } };
}

const READY_RESULT = {
    status: 'ready',
    summary: 'Added a children screen.',
    candidate_revision: 'candidate-2',
    has_candidate_changes: true,
    diagnostics: [],
    diff: { diff: '--- a\n+++ b\n+id: has_children\n', added: 4, removed: 1, changed_blocks: 2 },
    stop_reason: null,
    turn: {
      events: [
        { type: 'status', label: 'Thinking', status: 'thinking' },
        { type: 'tool_result', tool: 'get_interview_outline', label: 'Read interview structure', status: 'success' },
        { type: 'tool_result', tool: 'insert_question', label: 'Inserted new screen', status: 'success' },
      ],
    },
    session: { agent_session_id: 'agent-1', candidate_revision: 'candidate-2' },
};

const READY_TURN = TURN_STARTED;

// --- A session is created lazily, from the working-source snapshot ----------
{
  const harness = createHarness({
    responses: {
      '/api/agent/sessions': { success: true, data: { agent_session_id: 'agent-1' } },
      '/api/agent/sessions/agent-1/turn': TURN_STARTED,
      '/api/agent/sessions/agent-1/progress': finishedProgress(READY_RESULT),
    },
  });
  assert.strictEqual(harness.calls.length, 0, 'no session is created before the first message');

  harness.chat.send('Add a children screen').then(() => {
    const created = harness.calls[0];
    assert.strictEqual(created.path, '/api/agent/sessions');
    assert.strictEqual(created.body.raw_yaml, 'id: intro\nquestion: Hi\n');
    assert.strictEqual(created.body.base_revision, 'saved-revision');
    assert.strictEqual(created.body.project, 'default');
    assert.strictEqual(created.body.filename, 'main.yml');

    const turn = harness.calls[1];
    assert.strictEqual(turn.path, '/api/agent/sessions/agent-1/turn');
    assert.strictEqual(turn.body.selected_block_id, 'intro');
    // A turn is a write in progress: it must not be cancelled as stale.
    assert.strictEqual(turn.requestOptions.preventStale, false);

    assert.ok(harness.chat.canApply(), 'a ready turn with changes can be applied');
    const applyButton = buttonNamed(harness.container, 'Apply');
    assert.strictEqual(applyButton.disabled, false);

    const steps = findAll(harness.container, (node) => node.className === 'editor-agent-step-label');
    assert.deepStrictEqual(
      steps.map((node) => node.textContent),
      ['Read interview structure', 'Inserted new screen']
    );

    const summary = findAll(harness.container, (node) => node.tagName === 'summary')[0];
    assert.strictEqual(summary.textContent, 'Assistant changed 2 blocks · +4 −1 lines');
  }).catch((error) => {
    console.error(error);
    process.exit(1);
  });
}

// --- Apply is not offered for a turn that produced no valid change ----------
{
  const harness = createHarness({
    responses: {
      '/api/agent/sessions': { success: true, data: { agent_session_id: 'agent-1' } },
      '/api/agent/sessions/agent-1/turn': TURN_STARTED,
      '/api/agent/sessions/agent-1/progress': finishedProgress({
          status: 'failed',
          summary: 'I could not produce a valid edit.',
          has_candidate_changes: false,
          stop_reason: 'validation_repair_limit',
          diagnostics: [
            { level: 'error', block_id: 'children_names', message: 'A field is missing' },
          ],
          diff: null,
          turn: { events: [{ type: 'tool_result', tool: 'replace_question', label: 'Updated question', status: 'rejected' }] },
      }),
    },
  });
  harness.chat.send('Break the interview').then(() => {
    assert.ok(!harness.chat.canApply(), 'a failed turn cannot be applied');
    assert.strictEqual(buttonNamed(harness.container, 'Apply').disabled, true);

    const diagnostics = findAll(harness.container, (node) =>
      String(node.className).indexOf('editor-agent-diagnostic-error') !== -1);
    assert.strictEqual(diagnostics.length, 1);
    assert.strictEqual(diagnostics[0].textContent, 'children_names: A field is missing');

    const notes = findAll(harness.container, (node) => node.className === 'editor-agent-stop-reason');
    assert.strictEqual(notes[0].textContent, chatModule.STOP_REASON_NOTES.validation_repair_limit);

    // A rejected step is explained without dumping the model's reasoning.
    const steps = findAll(harness.container, (node) => node.className === 'editor-agent-step-label');
    assert.ok(/Attempted change failed/.test(steps[0].textContent));
  }).catch((error) => {
    console.error(error);
    process.exit(1);
  });
}

// --- A stale saved file is surfaced, not worked around ---------------------
{
  const staleError = new Error('Source changed since this agent session began.');
  staleError.code = 'agent_session_stale';
  const harness = createHarness({
    responses: {
      '/api/agent/sessions': { success: true, data: { agent_session_id: 'agent-1' } },
      '/api/agent/sessions/agent-1/turn': TURN_STARTED,
      '/api/agent/sessions/agent-1/progress': finishedProgress(READY_RESULT),
      '/api/agent/sessions/agent-1/apply': staleError,
    },
  });
  harness.chat.send('Add a screen')
    .then(() => harness.chat.apply())
    .then(() => {
      assert.strictEqual(harness.chat.getState(), 'stale');
      assert.strictEqual(harness.applied.length, 0, 'nothing is applied to the editor');
      const status = findAll(harness.container, (node) => node.className === 'editor-agent-status')[0];
      assert.ok(/Source changed/.test(status.textContent));
    }).catch((error) => {
      console.error(error);
      process.exit(1);
    });
}

// --- Apply hands the candidate to the editor ------------------------------
{
  const candidate = { raw_yaml: 'id: intro\nquestion: New\n', saved_revision: 'saved-revision' };
  const harness = createHarness({
    responses: {
      '/api/agent/sessions': { success: true, data: { agent_session_id: 'agent-1' } },
      '/api/agent/sessions/agent-1/turn': TURN_STARTED,
      '/api/agent/sessions/agent-1/progress': finishedProgress(READY_RESULT),
      '/api/agent/sessions/agent-1/apply': { success: true, data: candidate },
    },
  });
  harness.chat.send('Add a screen')
    .then(() => harness.chat.apply())
    .then(() => {
      assert.deepStrictEqual(harness.applied, [candidate]);
      const paths = harness.calls.map((call) => call.path);
      assert.ok(paths.indexOf('/api/agent/sessions/agent-1/apply') !== -1);
    }).catch((error) => {
      console.error(error);
      process.exit(1);
    });
}

// --- Reset clears the conversation and the candidate ----------------------
{
  const harness = createHarness({
    responses: {
      '/api/agent/sessions': { success: true, data: { agent_session_id: 'agent-1' } },
      '/api/agent/sessions/agent-1/turn': TURN_STARTED,
      '/api/agent/sessions/agent-1/progress': finishedProgress(READY_RESULT),
      '/api/agent/sessions/agent-1/reset': {
        success: true,
        data: { agent_session_id: 'agent-1', has_candidate_changes: false },
      },
    },
  });
  harness.chat.send('Add a screen')
    .then(() => harness.chat.reset())
    .then(() => {
      assert.ok(!harness.chat.canApply(), 'the diff and Apply disappear after Reset');
      const messages = findAll(harness.container, (node) =>
        String(node.className).indexOf('editor-agent-message-') !== -1);
      assert.strictEqual(messages.length, 0);
      const diffs = findAll(harness.container, (node) => node.className === 'editor-agent-diff');
      assert.strictEqual(diffs.length, 0);
    }).catch((error) => {
      console.error(error);
      process.exit(1);
    });
}

// --- An unmappable editor buffer stops the session before it starts -------
{
  const harness = createHarness({
    getWorkingSource: () => {
      throw new Error('Unsaved order-builder changes cannot be represented safely.');
    },
  });
  harness.chat.send('Change the order').then(() => {
    assert.strictEqual(harness.calls.length, 0, 'no request is made against stale saved YAML');
    assert.strictEqual(harness.chat.getState(), 'error');
    const status = findAll(harness.container, (node) => node.className === 'editor-agent-status')[0];
    assert.ok(/order-builder/.test(status.textContent));
  }).catch((error) => {
    console.error(error);
    process.exit(1);
  });
}

// --- Mechanical id problems are offered as a one-click fix ----------------
{
  const invalid = new Error('The assistant needs a valid interview to start from.');
  invalid.code = 'invalid_working_source';
  invalid.details = {
    can_auto_heal: true,
    repairable_count: 2,
    unrepairable_count: 0,
    repairs: [
      { kind: 'missing_id', new_id: 'what_is_your_name', summary: 'Gave the screen “What is your name?” the id what_is_your_name.' },
      { kind: 'duplicate_id', new_id: 'intro_2', previous_id: 'intro', summary: 'Renamed the repeated id intro to intro_2.' },
    ],
    diagnostics: [],
  };
  let healRequested = false;
  const harness = createHarness({
    responses: {
      '/api/agent/sessions': (body) => {
        if (!body.auto_heal) return invalid;
        healRequested = true;
        return {
          success: true,
          data: {
            agent_session_id: 'agent-1',
            repairs: invalid.details.repairs,
            has_candidate_changes: true,
          },
        };
      },
      '/api/agent/sessions/agent-1/turn': TURN_STARTED,
      '/api/agent/sessions/agent-1/progress': finishedProgress(READY_RESULT),
    },
  });

  harness.chat.send('Add a children screen').then(() => {
    const fixButton = buttonNamed(harness.container, 'Fix 2 problems and continue');
    assert.ok(fixButton, 'the repair offer is shown instead of a dead end');
    assert.strictEqual(healRequested, false, 'nothing is healed without the developer asking');

    const offered = findAll(harness.container, (node) => node.className === 'editor-agent-repair');
    assert.strictEqual(offered.length, 2, 'each repair is described before it happens');

    return harness.chat.apply().then(() => {
      assert.strictEqual(harness.applied.length, 0, 'a session that never started cannot apply');
      return fixButton.listeners.click();
    });
  }).then(() => {
    assert.strictEqual(healRequested, true);
    // The retry re-sends the request the developer already typed.
    const turns = harness.calls.filter((call) => /\/turn$/.test(call.path));
    assert.strictEqual(turns.length, 1);
    assert.strictEqual(turns[0].body.message, 'Add a children screen');
    assert.ok(harness.chat.canApply(), 'the healed session produces an applicable candidate');
  }).catch((error) => {
    console.error(error);
    process.exit(1);
  });
}

// --- A problem needing a human is not dressed up as a fix -----------------
{
  const invalid = new Error('The assistant needs a valid interview to start from.');
  invalid.code = 'invalid_working_source';
  invalid.details = {
    can_auto_heal: false,
    repairable_count: 1,
    unrepairable_count: 1,
    repairs: [],
    diagnostics: [{ level: 'error', block_id: 'intro', message: 'Undefined variable referenced: mystery' }],
  };
  const harness = createHarness({
    responses: { '/api/agent/sessions': invalid },
  });
  harness.chat.send('Change something').then(() => {
    assert.ok(!buttonNamed(harness.container, 'Fix 1 problem and continue'));
    const text = findAll(harness.container, (node) => node.className === 'editor-agent-repair-offer-text')[0];
    assert.ok(/needs a human decision/.test(text.textContent));
    const diagnostics = findAll(harness.container, (node) =>
      String(node.className).indexOf('editor-agent-diagnostic-error') !== -1);
    assert.strictEqual(diagnostics.length, 1);
  }).catch((error) => {
    console.error(error);
    process.exit(1);
  });
}

// --- No model configured: explain, do not offer a composer that fails ------
{
  const harness = createHarness({
    availability: {
      available: false,
      code: 'model_not_configured',
      message: 'The editing assistant needs a language model, and this server has ' +
        'no API key configured. Ask your server administrator to add an ' +
        '`openai api key` to the Configuration.',
    },
  });

  const detail = findAll(harness.container, (node) =>
    node.className === 'editor-agent-unavailable-detail')[0];
  assert.ok(detail, 'the reason is shown in the panel');
  assert.ok(/openai api key/.test(detail.textContent));

  // Nothing that would fail is offered.
  assert.strictEqual(findAll(harness.container, (n) => n.tagName === 'textarea').length, 0);
  assert.ok(!buttonNamed(harness.container, 'Send'));
  assert.ok(!buttonNamed(harness.container, 'Apply'));
  assert.ok(!buttonNamed(harness.container, 'Reset'));

  // The author can still see what the panel is.
  const title = findAll(harness.container, (node) =>
    String(node.className).indexOf('editor-agent-title') !== -1)[0];
  assert.strictEqual(title.textContent, 'Assistant');

  harness.chat.send('Add a screen').then(() => {
    assert.strictEqual(harness.calls.length, 0, 'no request is made without a model');
  }).catch((error) => {
    console.error(error);
    process.exit(1);
  });
}

// --- A running turn is unmistakable, and shows steps as they land ---------
{
  // The turn POST returns at once; the run itself is followed by polling, so
  // this drives the progress record from running to finished.
  let running = true;
  const harness = createHarness({
    responses: {
      '/api/agent/sessions': { success: true, data: { agent_session_id: 'agent-1' } },
      '/api/agent/sessions/agent-1/turn': TURN_STARTED,
      '/api/agent/sessions/agent-1/progress': () => ({
        success: true,
        data: {
          running,
          started_at: 0,
          events: [
            { type: 'status', label: 'Editing candidate', status: 'editing' },
            { type: 'tool_result', tool: 'get_interview_outline', label: 'Read interview structure', status: 'success' },
            { type: 'tool_result', tool: 'insert_question', label: 'Inserted new screen', status: 'success' },
          ],
          result: running ? null : READY_RESULT,
        },
      }),
    },
  });

  const sent = harness.chat.send('Add a children screen');

  // The banner is up the moment the turn starts, before any poll returns.
  const banner = findAll(harness.container, (n) => n.className === 'editor-agent-working')[0];
  assert.ok(banner, 'a working indicator is shown while the turn runs');
  assert.ok(findAll(banner, (n) => n.className === 'editor-agent-spinner')[0], 'the indicator animates');
  assert.ok(findAll(banner, (n) => n.className === 'editor-agent-working-bar')[0]);
  const elapsed = findAll(banner, (n) => n.className === 'editor-agent-working-time')[0];
  assert.ok(/^\d+s$/.test(elapsed.textContent), 'elapsed time is counted: ' + elapsed.textContent);

  // The composer is locked while work is in flight, and Stop is offered.
  assert.ok(buttonNamed(harness.container, 'Stop'), 'the run can be stopped');
  assert.strictEqual(findAll(harness.container, (n) => n.tagName === 'textarea')[0].disabled, true);

  setTimeout(() => {
    // Steps polled from the server appear while the turn is still running.
    const live = findAll(harness.container, (n) => n.className === 'editor-agent-step-label');
    assert.ok(live.length >= 2, 'steps taken so far are listed while running');
    assert.strictEqual(live[live.length - 1].textContent, 'Inserted new screen');
    const label = findAll(harness.container, (n) => n.className === 'editor-agent-working-label')[0];
    assert.strictEqual(label.textContent, 'Editing candidate…', 'the current activity is named');

    running = false;
    sent.then(() => {
      assert.ok(!findAll(harness.container, (n) => n.className === 'editor-agent-working')[0],
        'the indicator disappears once the turn finishes');
      assert.ok(harness.chat.canApply(), 'the polled result is what enables Apply');
    }).catch((error) => { console.error(error); process.exit(1); });
  }, 1700);
}

// --- A turn that dies server-side surfaces, rather than spinning forever ---
{
  const harness = createHarness({
    responses: {
      '/api/agent/sessions': { success: true, data: { agent_session_id: 'agent-1' } },
      '/api/agent/sessions/agent-1/turn': TURN_STARTED,
      '/api/agent/sessions/agent-1/progress': {
        success: true,
        data: {
          running: false,
          started_at: 0,
          events: [],
          error: { code: 'agent_turn_failed', message: 'The assistant could not complete that request.' },
        },
      },
    },
  });
  harness.chat.send('Do something').then(() => {
    assert.strictEqual(harness.chat.getState(), 'error');
    assert.ok(!findAll(harness.container, (n) => n.className === 'editor-agent-working')[0],
      'the working indicator is torn down on failure');
    assert.ok(!harness.chat.canApply());
  }).catch((error) => { console.error(error); process.exit(1); });
}

process.on('exit', function (code) {
  if (code === 0) console.log('editor_agent_chat.js checks passed');
});
