'use strict';

const assert = require('assert');
const AI = require('./data/static/editor_ai_assist.js');

const blocks = [
  {
    id: 'objects-1',
    ai_assists: [
      {
        name: 'story_ai',
        task: 'rewrite',
        settings: { task: 'rewrite', source: 'story', model: 'small' },
        computed: [],
        review_block_id: 'review story_reviewed',
        review_question: 'Review your story',
        review_fields: [{ variable: 'story_reviewed', label: '', datatype: 'area', choices: [] }],
      },
      {
        name: 'notice_ai',
        task: 'extract',
        settings: {
          task: 'extract',
          source: 'notice',
          outputs: { hearing_date: 'When the hearing is', court: 'Court' },
        },
        computed: [],
        review_block_id: 'review hearing_date',
        review_question: 'Check',
        review_fields: [
          { variable: 'hearing_date', label: 'Hearing date', datatype: 'date', choices: [] },
          { variable: 'court', label: 'Court', datatype: 'text', choices: [] },
        ],
      },
    ],
  },
];

// Every task the runtime supports is offered, and each says what it needs.
assert.deepStrictEqual(
  AI.TASKS.map((t) => t.value).sort(),
  ['classify', 'extract', 'extract_file', 'goal', 'prompt', 'rewrite', 'summarize', 'translate'],
);
AI.TASKS.forEach((t) => assert.ok(['text', 'fields', 'choice'].includes(t.output)));

assert.strictEqual(AI.assistForSource(blocks, 'story').name, 'story_ai');
assert.strictEqual(AI.assistForSource(blocks, 'other'), null);
assert.strictEqual(AI.suggestedOutput('users[0].story', 'summarize'), 'users_story_summary');

// Reopening shows the saved settings; a description equal to its label is not repeated.
const form = AI.formState(AI.assistByName(blocks, 'notice_ai'), 'notice');
assert.deepStrictEqual(form.outputs, [
  { label: 'Hearing date', variable: 'hearing_date', datatype: 'date', description: 'When the hearing is' },
  { label: 'Court', variable: 'court', datatype: 'text', description: '' },
]);
const story = AI.formState(AI.assistByName(blocks, 'story_ai'), 'story');
assert.strictEqual(story.output, 'story_reviewed');
assert.strictEqual(story.model, 'small');
// Switching kinds starts from that kind's defaults.
assert.strictEqual(AI.formState(AI.assistByName(blocks, 'story_ai'), 'story', 'translate').output, 'story_translated');

const config = AI.configFromForm(Object.assign({}, story, { inputs: 'a\n b, c', askPermission: false }));
assert.deepStrictEqual(config.inputs, ['a', 'b', 'c']);
assert.strictEqual(config.ask_permission, false);
assert.strictEqual(config.output, 'story_reviewed');
assert.ok(!('outputs' in config));

assert.strictEqual(AI.inputDatatypeFor('extract_file', 'area'), 'file');
assert.strictEqual(AI.inputDatatypeFor('extract_file', 'files'), null);
assert.strictEqual(AI.inputDatatypeFor('rewrite', 'text'), 'area');
assert.strictEqual(AI.inputDatatypeFor('rewrite', 'areaC'), null);

// The order builder groups "ask, then review" into one AI step, at any depth,
// and leaves an unrelated pair alone.
const screen = (id, invoke) => ({ id, kind: 'screen', invoke });
const merged = AI.mergeOrderSteps(
  [
    screen('s1', 'intro'),
    screen('s2', 'story'),
    screen('s3', 'story_reviewed'),
    { id: 'c', kind: 'condition', condition: 'x', children: [screen('s4', 'notice_screen'), screen('s5', 'hearing_date')], else_children: [] },
    screen('s6', 'hearing_date'),
  ],
  blocks,
  (source) => (source === 'notice' ? ['notice_screen'] : []),
);
assert.deepStrictEqual(merged.map((s) => s.kind), ['screen', 'ai', 'condition', 'screen']);
assert.strictEqual(merged[1].assist, 'story_ai');
assert.deepStrictEqual(merged[1].children.map((s) => s.id), ['s2', 's3']);
assert.strictEqual(merged[2].children[0].kind, 'ai');
// Merging again changes nothing.
assert.deepStrictEqual(AI.mergeOrderSteps(merged, blocks), merged);

const added = AI.newOrderStep(AI.assistByName(blocks, 'notice_ai'), 'notice_screen');
assert.deepStrictEqual(added.children.map((s) => s.invoke), ['notice_screen', 'hearing_date']);

console.log('editor_ai_assist.js tests passed');
