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

// A screen carrying both a question and an attachment keeps the question
// editor, which is where the "Edit attachment field mappings" button lives.
// A standalone attachment block still gets the plain attachment card.
const routed = [];
const canvas = {
  window: {ALWeaverSerializers: require('./data/static/editor_serializers.js')},
  state: {project: 'p', questionEditMode: 'preview'},
  canvasContent: {innerHTML: ''},
  selected: null,
  renderProjectSelector: () => { routed.push('project'); },
  renderQuestionBlock: () => { routed.push('question'); },
  renderReviewBlock: () => { routed.push('review'); },
  renderCommentedBlock: () => { routed.push('commented'); },
  renderCodeBlock: () => { routed.push('code'); },
  renderObjectsBlock: () => { routed.push('objects'); },
  renderGenericBlock: () => { routed.push('generic'); },
  renderAttachmentBlock: () => { routed.push('attachment'); },
  emptyCanvasHtml: () => '',
  esc: (value) => String(value),
};
canvas.getSelectedBlock = () => canvas.selected;
vm.createContext(canvas);
const templateStart = source.indexOf('  function isTemplateEditorBlock(');
vm.runInContext(source.slice(templateStart, source.indexOf('\n  }', templateStart) + 4), canvas);
const helperStart = source.indexOf('  function isQuestionEditorBlock(');
vm.runInContext(source.slice(helperStart, source.indexOf('\n  }', helperStart) + 4), canvas);
const canvasStart = source.indexOf('  function renderBlockCanvas(');
vm.runInContext(source.slice(canvasStart, source.indexOf('\n  }', canvasStart) + 4), canvas);
canvas.selected = {type: 'question', title: 'Plain', data: {}};
canvas.renderBlockCanvas();
canvas.selected = {type: 'attachment', title: 'Your documents',
  data: {question: 'Your documents', attachment: {'variable name': 'petition[i]'}}};
canvas.renderBlockCanvas();
assert.deepStrictEqual(routed, ['question', 'question']);
canvas.selected = {type: 'attachment', title: 'Petition',
  data: {attachment: {'variable name': 'petition[i]'}}};
canvas.renderBlockCanvas();
assert.deepStrictEqual(routed, ['question', 'question', 'attachment']);

// The standalone attachment is edited in place: every setting Weaver can
// write gets a control, and the rest are shown with what they do.
const inline = {
  state: {project: 'p', filename: 'main.yml', revision: 'r1'},
  esc: (value) => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;'),
  isQuestionEditorBlock: () => false,
};
vm.createContext(inline);
const settingsStart = source.indexOf('  var ATTACHMENT_DOCS_URL');
vm.runInContext(source.slice(settingsStart, source.indexOf('  var _attachmentEditor = null;', settingsStart)), inline);
for (const name of [
  'attachmentDraftKey', 'attachmentKindOf', 'attachmentSettingIsEditable',
  'attachmentDraftValue', 'renderAttachmentSetting', 'renderAttachmentFieldRows',
  'renderAttachmentReadOnlySetting', 'renderAttachmentSection', 'attachmentEditorUpdates',
]) {
  const begin = source.indexOf(`  function ${name}(`);
  assert.ok(begin > 0, name);
  vm.runInContext(source.slice(begin, source.indexOf('\n  }\n', begin) + 4), inline);
}
const pdfAttachment = {
  index: 0, kind: 'pdf', template: 'form.pdf', dynamic: true,
  rows: [{name: 'amount', value: '${ amount }', editable: true}],
  template_fields: ['amount', 'signature'],
  settings: [
    {key: 'name', type: 'str', value: 'Petition'},
    {key: 'pdf template file', type: 'str', value: 'form.pdf'},
    {key: 'filename', type: 'str', value: '${ name_of_file }'},
    {key: 'editable', type: 'bool', value: false},
    {key: 'skip undefined', type: 'str', value: '${ flag }'},
    {key: 'field code', type: 'complex', value: 'x: y'},
    {key: 'mystery option', type: 'str', value: 'z'},
  ],
};
const editor = {status: 'ready', draft: {}, data: {attachments: [pdfAttachment]}};
let section = inline.renderAttachmentSection(editor, pdfAttachment, 1);
assert.ok(section.includes('data-attachment-setting="name"'));
assert.ok(section.includes('value="Petition"'));
assert.ok(section.includes('list="attachment-template-files-pdf"'), 'a PDF template only suggests PDFs');
assert.ok(/data-attachment-setting="editable"(?![^>]*checked)/.test(section));
assert.ok(section.includes('data-attachment-setting="pdf/a"'));
assert.ok(!section.includes('data-attachment-setting="tagged pdf"'), 'Word-only switch on a PDF');
assert.ok(!section.includes('data-attachment-setting="valid formats"'), 'Word-only formats on a PDF');
assert.ok(!section.includes('data-attachment-setting="skip undefined"'), 'computed value offered as a switch');
assert.ok(section.includes('<code>skip undefined</code>'));
assert.ok(section.includes('Computed here, so edit it in Block YAML.'));
assert.ok(section.includes('<code>field code</code>'));
assert.ok(section.includes('computed by Python expressions'));
assert.ok(section.includes('<code>mystery option</code>'));
assert.ok(section.includes('Weaver does not describe this setting yet'));
assert.ok(section.includes('data-attachment-field="signature"'));
assert.ok(section.includes('Field mappings'));
assert.ok(!section.includes('data-edit-attachment-mappings'));
// A description may span lines, which an <input> would flatten.
assert.ok(/<textarea[^>]*data-attachment-setting="description"/.test(section));

assert.strictEqual(inline.attachmentEditorUpdates(editor).length, 0);
const key = (kind, name) => inline.attachmentDraftKey(0, kind, name);
editor.draft[key('setting', 'editable')] = false; // unchanged
editor.draft[key('setting', 'pdf/a')] = false; // the default, absent
editor.draft[key('setting', 'skip undefined')] = true; // read-only
editor.draft[key('field', 'signature')] = '';
assert.strictEqual(inline.attachmentEditorUpdates(editor).length, 0);
editor.draft[key('setting', 'name')] = 'Motion';
editor.draft[key('setting', 'pdf/a')] = true;
editor.draft[key('field', 'signature')] = '${ users[0].signature }';
assert.deepStrictEqual(JSON.parse(JSON.stringify(inline.attachmentEditorUpdates(editor))), [{
  index: 0,
  values: {signature: '${ users[0].signature }'},
  settings: {name: 'Motion', 'pdf/a': true},
}]);
section = inline.renderAttachmentSection(editor, pdfAttachment, 1);
assert.ok(section.includes('value="Motion"'), 'a re-render keeps the draft');

const docxAttachment = {
  index: 0, kind: 'docx', template: 'letter.docx', rows: [], template_fields: [],
  settings: [
    {key: 'docx template file', type: 'str', value: 'letter.docx'},
    {key: 'name', type: 'str', value: 'Line one\nLine two'},
  ],
};
section = inline.renderAttachmentSection({draft: {}}, docxAttachment, 1);
assert.ok(section.includes('data-attachment-setting="tagged pdf"'));
assert.ok(section.includes('data-attachment-format="pdf" checked'));
assert.ok(section.includes('data-attachment-format="docx" checked'));
assert.ok(!section.includes('data-attachment-setting="editable"'));
assert.ok(section.includes('reads interview variables directly'));
assert.ok(!section.includes('Other settings'));
assert.ok(/<textarea[^>]*data-attachment-setting="name"[^>]*>\nLine one\nLine two</.test(section));

// A commented list would lose its comments if rewritten.
docxAttachment.settings.push({key: 'valid formats', type: 'list', value: ['pdf'], commented: true});
section = inline.renderAttachmentSection({draft: {}}, docxAttachment, 1);
assert.ok(!section.includes('data-attachment-format='));
assert.ok(section.includes('It has comments inside'));

// A blank format list cannot be rewritten in place, so it stays read-only.
docxAttachment.settings[2] = {key: 'valid formats', type: 'null', value: ''};
section = inline.renderAttachmentSection({draft: {}}, docxAttachment, 1);
assert.ok(!section.includes('data-attachment-format='));

// Markdown documents have no template, so no template-only controls or mappings.
const markdown = {
  index: 0, kind: 'other', template: '', rows: [], template_fields: [], dynamic: false,
  settings: [
    {key: 'name', type: 'str', value: 'Notes'},
    {key: 'content', type: 'str', value: 'Hello'},
    {key: 'allow privileges', type: 'list', value: ['admin']},
  ],
};
section = inline.renderAttachmentSection({draft: {}}, markdown, 1);
assert.ok(section.includes('Markdown document'));
assert.ok(!section.includes('Word template'));
assert.ok(!section.includes('data-attachment-setting="tagged pdf"'));
assert.ok(!section.includes('data-attachment-format='));
assert.ok(!section.includes('Field mappings'));
assert.ok(section.includes('no fields to map'));
assert.ok(section.includes('used instead of a template'));
assert.ok(section.includes('Privileges (such as admin)'));

// Saving must follow the same dispatch as rendering, including in YAML mode.
const saveStart = source.indexOf('  function getBlockYamlForSave(');
vm.runInContext(source.slice(saveStart, source.indexOf('\n  }', saveStart) + 4), canvas);
canvas.serializeQuestionBlockToYaml = () => 'question: Edited question\nfields:\n  - Name: users[0].name';
canvas.getSourceEditorValue = () => 'question: Edited in YAML';
for (const type of ['question', 'attachment']) {
  const block = {type, yaml: 'question: Original', data: {question: 'Original', attachment: {}}};
  assert.ok(canvas.getBlockYamlForSave(block).includes('question: Edited question'));
}
assert.strictEqual(canvas.getBlockYamlForSave({type: 'attachment', data: {}, yaml: 'attachment: original'}), 'attachment: original');
canvas.state.questionEditMode = 'yaml';
assert.strictEqual(canvas.getBlockYamlForSave({type: 'attachment', data: {question: 'Original'}, yaml: 'original'}), 'question: Edited in YAML');

// Template scope remains explicit in a project with multiple interview files.
const templateScope = {
  state: {
    filename: 'second.yml',
    files: [{filename: 'first.yml'}, {filename: 'second.yml'}],
    documents: {templates: {'form.pdf': {status: 'not_imported'}}},
  },
  esc: (value) => String(value).replaceAll('&', '&amp;').replaceAll('"', '&quot;'),
};
vm.createContext(templateScope);
for (const name of ['renderTemplateInterviewSelector', 'renderUnimportedTemplatesCard']) {
  const begin = source.indexOf(`  function ${name}(`);
  vm.runInContext(source.slice(begin, source.indexOf('\n  }', begin) + 4), templateScope);
}
let selector = templateScope.renderTemplateInterviewSelector();
assert.ok(selector.includes('data-template-interview="second.yml" aria-current="true"'));
assert.ok(selector.includes('data-template-interview="first.yml"'));
assert.ok(selector.includes('>Change</button>'));
assert.ok(selector.includes('class="list-group mt-2" hidden'));
assert.ok(!selector.includes('<select'));
assert.ok(templateScope.renderUnimportedTemplatesCard().includes('Templates not imported into second.yml'));
templateScope.state.templateImportBusy = 'form.pdf';
assert.ok(templateScope.renderTemplateInterviewSelector().includes('aria-controls="template-interview-choices" disabled'));
templateScope.state.templateImportBusy = null;
templateScope.state.filename = 'first.yml';
templateScope.state.documents = {templates: {'form.pdf': {status: 'attached'}}};
assert.ok(templateScope.renderTemplateInterviewSelector().includes('data-template-interview="first.yml" aria-current="true"'));
assert.strictEqual(templateScope.renderUnimportedTemplatesCard(), '');

Object.assign(templateScope, {
  API: '/al/editor',
  playgroundState: {user_id: 12},
  outlineList: {innerHTML: ''},
  getSectionFiles: () => [{filename: 'form.pdf'}],
  getSectionFromView: () => 'template',
  sectionTypeTag: () => 'PDF',
  supportsDashboardEditor: () => false,
  initOutlineSortable: () => {},
  templateStatus: () => ({status: 'not_imported'}),
});
Object.assign(templateScope.state, {
  currentView: 'templates', searchQuery: '', sectionSelectedFile: {},
});
const outlineStart = source.indexOf('  function renderSectionOutline(');
const rawUrlStart = source.indexOf('  function playgroundRawUrl(');
vm.runInContext(source.slice(rawUrlStart, source.indexOf('\n  }', rawUrlStart) + 4), templateScope);
vm.runInContext(source.slice(outlineStart, source.indexOf('\n  }', outlineStart) + 4), templateScope);
templateScope.renderSectionOutline();
const outlineHtml = templateScope.outlineList.innerHTML;
assert.ok(outlineHtml.indexOf('change-template-interview') < outlineHtml.indexOf('data-section-filename'));
assert.ok(outlineHtml.includes('form.pdf</div><span class="editor-outline-status"'));
assert.ok(outlineHtml.includes('title="Not imported into first.yml">Not imported</span>'));
assert.ok(outlineHtml.includes('playground_user_id=12'));
templateScope.state.searchQuery = 'no match';
templateScope.renderSectionOutline();
assert.ok(templateScope.outlineList.innerHTML.includes('change-template-interview'));
assert.ok(templateScope.outlineList.innerHTML.includes('No files found'));
