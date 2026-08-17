'use strict';

const assert = require('assert');
const preview = require('./data/static/editor_screen_preview.js');

function fieldLabels(fields) {
  return fields.map((f) => f.label);
}

// --- AssemblyLine name_fields() ---------------------------------------------

{
  const call = preview.parseMethodCall('users[0].name_fields()');
  assert.deepStrictEqual(call, { object: 'users[0]', method: 'name_fields', args: '' });

  const { fields } = preview.expandALMethod(call);
  assert.deepStrictEqual(fieldLabels(fields), ['First name', 'Middle name', 'Last name', 'Suffix']);
  assert.strictEqual(fields[0].field, 'users[0].name.first');
  assert.strictEqual(fields[1].required, false, 'middle name is optional');
  assert.ok(Array.isArray(fields[3].choices) && fields[3].choices.length > 0, 'suffix has choices');
}

{
  const { fields } = preview.expandALMethod(
    preview.parseMethodCall('users[0].name_fields(show_suffix=False, show_title=True)')
  );
  assert.deepStrictEqual(fieldLabels(fields), ['Title (optional)', 'First name', 'Middle name', 'Last name']);
}

{
  const { fields } = preview.expandALMethod(
    preview.parseMethodCall("other_parties[0].name_fields(person_or_business='business')")
  );
  assert.deepStrictEqual(fieldLabels(fields), ['Name of business or organization']);
  assert.strictEqual(fields[0].field, 'other_parties[0].name.first');
}

{
  // person_or_business=None asks first, then branches with show-if conditions.
  const { fields } = preview.expandALMethod(
    preview.parseMethodCall('other_parties[0].name_fields(person_or_business=None)')
  );
  assert.strictEqual(fields[0].label, 'Is this a person, or a business?');
  assert.strictEqual(fields[0]['input type'], 'radio');
  assert.deepStrictEqual(fields[1]['show if'], {
    variable: 'other_parties[0].person_type',
    is: 'ALIndividual',
  });
  assert.strictEqual(fields[fields.length - 1].label, 'Name of business or organization');
}

{
  const { fields } = preview.expandALMethod(
    preview.parseMethodCall("users[0].name_fields(required={'middle': False, 'last': True})")
  );
  const last = fields.find((f) => f.field === 'users[0].name.last');
  assert.strictEqual(last.required, true, 'required= keys are prefixed with the object name');
}

// --- AssemblyLine address_fields() ------------------------------------------

{
  const { fields } = preview.expandALMethod(preview.parseMethodCall('users[0].address_fields()'));
  assert.deepStrictEqual(fieldLabels(fields), [
    'Street address', 'Apartment', 'City', 'State', 'Zip or postal code',
  ]);
  assert.strictEqual(fields[0].field, 'users[0].address.address');
  assert.strictEqual(fields[3].code, "states_list(country_code='US')");
}

{
  const { fields } = preview.expandALMethod(
    preview.parseMethodCall('users[0].address_fields(allow_no_address=True, show_county=True)')
  );
  assert.strictEqual(fields[0].label, 'I do not have an address');
  assert.strictEqual(fields[0].datatype, 'yesno');
  assert.strictEqual(fields[1].datatype, 'area');
  assert.strictEqual(fields[2]['hide if'], 'users[0].address.has_no_address');
  assert.ok(fieldLabels(fields).includes('County'));
}

{
  const { fields } = preview.expandALMethod(
    preview.parseMethodCall('users[0].address_fields(show_country=True)')
  );
  assert.ok(fieldLabels(fields).includes('Country'));
  assert.ok(fieldLabels(fields).includes('State / Province'));
  assert.ok(fieldLabels(fields).includes('Postal code'));
}

{
  // ALIndividual delegates to self.address, but a receiver already ending in
  // .address must not become users[0].address.address.
  const { fields } = preview.expandALMethod(
    preview.parseMethodCall('users[0].address.address_fields()')
  );
  assert.strictEqual(fields[0].field, 'users[0].address.address');
}

// --- gender / pronoun / language --------------------------------------------

{
  const { fields } = preview.expandALMethod(preview.parseMethodCall('users[0].gender_fields()'));
  assert.deepStrictEqual(fieldLabels(fields), ['Gender', 'Self-described gender']);
  assert.strictEqual(fields[0].choices.length, 6);
  assert.deepStrictEqual(fields[1]['show if'], { variable: 'users[0].gender', is: 'self-described' });
}

{
  const forUser = preview.expandALMethod(preview.parseMethodCall('users[0].pronoun_fields()')).fields;
  assert.strictEqual(forUser[0].label, 'Check one or more pronouns that you want people to use to refer to you');
  assert.strictEqual(forUser[0].datatype, 'checkboxes');
  assert.strictEqual(forUser[0]['none of the above'], 'Prefer not to say');
  assert.ok(!forUser[0].choices.some((c) => c.value === 'unknown'),
    'show_unknown="guess" hides Unknown for users[0]');

  const forOther = preview.expandALMethod(
    preview.parseMethodCall('other_parties[0].pronoun_fields()')
  ).fields;
  assert.ok(forOther[0].choices.some((c) => c.value === 'unknown'),
    'show_unknown="guess" shows Unknown for anyone else');
}

{
  const { fields } = preview.expandALMethod(preview.parseMethodCall('users[0].language_fields()'));
  assert.strictEqual(fields[0]['input type'], 'radio');
  const asDropdown = preview.expandALMethod(
    preview.parseMethodCall("users[0].language_fields(style='dropdown')")
  ).fields;
  assert.strictEqual(asDropdown[0]['input type'], undefined);
}

// --- runtime expressions we cannot evaluate ---------------------------------

{
  const { notes } = preview.expandALMethod(
    preview.parseMethodCall('users[0].name_fields(show_suffix=al_show_suffix)')
  );
  assert.strictEqual(notes.length, 1);
  assert.ok(notes[0].includes('show_suffix=al_show_suffix'));
}

// --- reading the several shapes of a fields: row -----------------------------

{
  const shorthand = preview.describeField({ 'Your first name': 'user_first_name' }).fields[0];
  assert.strictEqual(shorthand.label, 'Your first name');
  assert.strictEqual(shorthand.variable, 'user_first_name');
  assert.strictEqual(shorthand.datatype, 'text');

  const expanded = preview.describeField({
    label: 'Pick one',
    field: 'choice',
    choices: ['One', 'Two'],
    required: false,
  }).fields[0];
  assert.strictEqual(expanded.datatype, 'dropdown', 'choices with no datatype is a dropdown');
  assert.strictEqual(expanded.required, false);
  assert.deepStrictEqual(expanded.choices, [
    { label: 'One', value: 'One' },
    { label: 'Two', value: 'Two' },
  ]);

  const note = preview.describeField({ note: 'Read **this** first' }).fields[0];
  assert.strictEqual(note.kind, 'note');

  const yesno = preview.describeField({ 'Do you agree?': 'agreed', datatype: 'yesno' }).fields[0];
  assert.strictEqual(yesno.datatype, 'yesno');

  const noLabel = preview.describeField({ 'no label': 'anything_else', datatype: 'area' }).fields[0];
  assert.strictEqual(noLabel.noLabel, true);
  assert.strictEqual(noLabel.datatype, 'area');
}

// --- Docassemble markup ------------------------------------------------------

{
  const rendered = preview.renderQuestion({
    question: 'What is your **name**?',
    subquestion: 'We need this for the form.',
    fields: [
      { code: 'users[0].name_fields()' },
      { 'Do you agree?': 'agreed', datatype: 'yesno' },
      { label: 'How many?', field: 'count', datatype: 'integer' },
      { label: 'Tell us more', field: 'more', datatype: 'area' },
      { label: 'Pick one', field: 'pick', choices: ['A', 'B'], 'input type': 'radio' },
      { note: 'A closing note' },
    ],
  });
  const html = rendered.html;

  assert.ok(html.includes('id="daquestion"'));
  assert.ok(html.includes('<h1 class="h3" id="daMainQuestion">What is your <strong>name</strong>?</h1>'));
  assert.ok(html.includes('class="da-subquestion"'));
  assert.ok(html.includes('class="col-md-4 col-form-label da-form-label datext-right">First name</label>'));
  assert.ok(html.includes('class="col-md-8 dafieldpart"'));
  assert.ok(html.includes('form-select dasingleselect'), 'the suffix list renders as a select');
  assert.ok(html.includes('type="number" step="1"'), 'integer renders as a number input');
  assert.ok(html.includes('<textarea alt="Input box" class="form-control datextarea"'));
  assert.ok(html.includes('da-field-group da-field-checkbox'), 'yesno renders as a labelauty checkbox');
  assert.ok(html.includes('da-field-group da-field-radio'), 'input type radio renders as labelauty radios');
  assert.ok(html.includes('data-labelauty="Do you agree?|Do you agree?"'));
  assert.ok(html.includes('da-field-container-emptylabel'), 'yesno carries its label inside the checkbox');
  assert.ok(html.includes('darequired'), 'required fields get the asterisk class');
  assert.ok(html.includes('class="da-button-set da-field-buttons"'));
  assert.ok(html.includes('>Continue</button>'));
  assert.ok(html.includes('<div class="da-container da-form-group danote">'));
  assert.strictEqual(rendered.fieldCount, 9, 'name_fields() expands to four rows');
}

{
  // Conditional fields are annotated rather than hidden, so the author can see
  // every branch of the screen at once.
  const rendered = preview.renderQuestion({
    question: 'Who are you?',
    fields: [{ code: 'users[0].gender_fields()' }],
  });
  assert.ok(rendered.html.includes('data-dapv-condition="show if: users[0].gender is &quot;self-described&quot;"'));
}

{
  const rendered = preview.renderQuestion({
    question: 'How much?',
    fields: [{ label: 'Amount', field: 'amount', datatype: 'currency' }],
  });
  assert.ok(rendered.html.includes('<div class="input-group"><span class="input-group-text">$</span>'));
  assert.ok(rendered.html.includes('class="form-control dacurrency"'));
}

{
  const rendered = preview.renderQuestion({
    question: 'Sign up',
    fields: [{ label: 'Email', field: 'email', datatype: 'email', help: 'We will not share it.' }],
  });
  assert.ok(rendered.html.includes('type="email"'));
  assert.ok(rendered.html.includes('data-bs-toggle="popover"'), 'field help renders as a popover trigger');
}

// --- the iframe document -----------------------------------------------------

{
  const doc = preview.buildDocument({ question: 'Hello', fields: [] }, {});
  assert.ok(doc.startsWith('<!DOCTYPE html>'));
  assert.ok(doc.includes('href="/static/bootstrap/css/bootstrap.min.css"'));
  assert.ok(doc.includes('href="/static/app/bundle.css"'), 'Docassemble ships its interview CSS here on 1.9 and 1.10');
  assert.ok(doc.includes('src="/static/app/jquery.min.js"'));
  assert.ok(doc.includes('src="/static/labelauty/source/jquery-labelauty.min.js"'));
  assert.ok(doc.includes('.labelauty({class: "labelauty da-active-invisible dafullwidth"})'));
  assert.ok(doc.includes('<body class="dabody">'));
  assert.ok(doc.includes('data-bs-theme="light"'));
}

{
  const doc = preview.buildDocument({ question: 'Hello', fields: [] }, {
    theme: 'dark',
    assets: { bootstrapCss: '/packagestatic/docassemble.ALThemeTemplate/al_theme.css' },
    extraCss: ['/packagestatic/docassemble.AssemblyLine/styles.css'],
  });
  assert.ok(doc.includes('data-bs-theme="dark"'));
  assert.ok(doc.includes('href="/packagestatic/docassemble.ALThemeTemplate/al_theme.css"'));
  assert.ok(doc.includes('href="/packagestatic/docassemble.AssemblyLine/styles.css"'));
  assert.ok(!doc.includes('/static/bootstrap/css/bootstrap.min.css'), 'the interview theme replaces the default');
}

{
  const doc = preview.buildDocument({
    question: 'Hi',
    fields: [{ code: 'users[0].name_fields(show_suffix=some_variable)' }],
  }, {});
  assert.ok(doc.includes('Preview notes'));
  assert.ok(doc.includes('show_suffix=some_variable'));
}

// --- label layout ------------------------------------------------------------

{
  // Docassemble's default is a label to the LEFT of the field. Only
  // `features: labels above fields: True` moves it on top.
  assert.strictEqual(preview.DEFAULT_LABEL_LAYOUT, 'horizontal');
  assert.strictEqual(preview.labelLayoutFromFeatures({}), null);
  assert.strictEqual(preview.labelLayoutFromFeatures(null), null);
  assert.strictEqual(preview.labelLayoutFromFeatures({ 'labels above fields': true }), 'above');
  assert.strictEqual(preview.labelLayoutFromFeatures({ 'labels above fields': false }), 'horizontal');
  assert.strictEqual(preview.labelLayoutFromFeatures({ 'floating labels': true }), 'floating');
}

{
  const block = { question: 'Q', fields: [{ label: 'First name', field: 'a' }] };

  const dflt = preview.renderQuestion(block, {});
  assert.strictEqual(dflt.labelLayout, 'horizontal', 'no layout given means Docassemble default');
  assert.ok(dflt.html.includes('class="col-md-4 col-form-label da-form-label datext-right"'));
  assert.ok(dflt.html.includes('class="col-md-8 dafieldpart"'));
  assert.ok(dflt.html.includes('da-form-group row'), 'horizontal fields are a Bootstrap row');

  const above = preview.renderQuestion(block, { labelLayout: 'above' });
  assert.ok(above.html.includes('class="form-label da-top-label"'));
  assert.ok(!above.html.includes('col-form-label'));

  const floating = preview.renderQuestion(block, { labelLayout: 'floating' });
  assert.ok(floating.html.includes('da-form-group-floating form-floating mb-3'));
  assert.ok(floating.html.includes('placeholder="First name"'));
  assert.ok(floating.html.indexOf('<label') > floating.html.indexOf('<input'),
    'a floating label follows its input');
}

{
  // Per-field modifiers override the interview-wide setting in both directions.
  const optOut = preview.renderQuestion({
    question: 'Q',
    fields: [{ label: 'Name', field: 'a', 'label above field': false }],
  }, { labelLayout: 'above' });
  assert.ok(optOut.html.includes('col-form-label'), 'label above field: False falls back to horizontal');

  const optIn = preview.renderQuestion({
    question: 'Q',
    fields: [{ label: 'Name', field: 'a', 'label above field': true }],
  }, { labelLayout: 'horizontal' });
  assert.ok(optIn.html.includes('da-top-label'));
}

{
  // yesno keeps its label inside the checkbox in every layout, and Docassemble
  // makes it optional unless the author says otherwise.
  const yesno = { question: 'Q', fields: [{ 'Do you agree?': 'agreed', datatype: 'yesno' }] };
  const horizontal = preview.renderQuestion(yesno, {});
  assert.ok(horizontal.html.includes('offset-md-4 col-md-8 dafieldpart'));
  assert.ok(!horizontal.html.includes('darequired'), 'yesno is not required by default');
  const above = preview.renderQuestion(yesno, { labelLayout: 'above' });
  assert.ok(above.html.includes('da-field-container-nolabel'));
  assert.ok(!above.html.includes('offset-md-4'));
}

{
  // Radio and checkbox groups are an ARIA group, not a <label> for one control.
  const rendered = preview.renderQuestion({
    question: 'Q',
    fields: [{ code: 'users[0].pronoun_fields()' }],
  }, { labelLayout: 'above' });
  assert.ok(rendered.html.includes('da-fieldset'));
  assert.ok(rendered.html.includes('aria-labelledby="da-label-0"'));
  assert.ok(rendered.html.includes('<div id="da-label-0" class="da-legend form-label da-top-label">'));
  assert.ok(rendered.html.includes('da-field-container-inputtype-checkboxes'));
}

// --- the button set ----------------------------------------------------------

{
  // AssemblyLine's house style: the back button sits on the left and is called
  // "Undo". Docassemble emits it before Continue for exactly that reason.
  assert.strictEqual(preview.DEFAULT_BACK_BUTTON_LABEL, 'Undo');
  const rendered = preview.renderQuestion({ question: 'Q', fields: [] }, {});
  const buttons = rendered.html.split('<fieldset class="da-button-set')[1];
  assert.ok(buttons.indexOf('daquestionbackbutton') < buttons.indexOf('type="submit"'),
    'the back button comes first, so it renders to the left');
  assert.ok(buttons.includes('>Undo</button>'));
  assert.ok(buttons.includes('>Continue</button>'));
}

{
  const renamed = preview.renderQuestion({ question: 'Q', fields: [] }, {
    backButtonLabel: 'Back',
    continueButtonLabel: 'Next',
  });
  assert.ok(renamed.html.includes('>Back</button>'));
  assert.ok(renamed.html.includes('>Next</button>'));

  const perScreen = preview.renderQuestion({
    question: 'Q',
    fields: [],
    'continue button label': 'Finish',
  }, { continueButtonLabel: 'Next' });
  assert.ok(perScreen.html.includes('>Finish</button>'),
    "the screen's own continue label wins over the interview default");

  const hidden = preview.renderQuestion({ question: 'Q', fields: [] }, { showBackButton: false });
  assert.ok(!hidden.html.includes('daquestionbackbutton'));
}

// --- literal HTML ------------------------------------------------------------

{
  // Interviews embed Bootstrap alerts and cards; Docassemble's Markdown passes
  // raw HTML through, so the preview must render it rather than escape it.
  const rendered = preview.renderQuestion({
    question: 'Q',
    subquestion: 'Before you start:\n\n<div class="alert alert-warning" role="alert">\n  You will need your <strong>case number</strong>.\n</div>\n\nThen continue.',
    fields: [
      { html: '<div class="card"><div class="card-body">A card</div></div>' },
      { note: 'A note with an <span class="badge text-bg-info">inline badge</span>' },
    ],
  });
  assert.ok(rendered.html.includes('<div class="alert alert-warning" role="alert">'),
    'a block-level HTML element renders as HTML');
  assert.ok(rendered.html.includes('<strong>case number</strong>'));
  assert.ok(rendered.html.includes('<p>Then continue.</p>'), 'markdown resumes after the HTML block');
  assert.ok(rendered.html.includes('<div class="card"><div class="card-body">A card</div></div>'));
  assert.ok(rendered.html.includes('<span class="badge text-bg-info">inline badge</span>'));
  assert.ok(!rendered.html.includes('&lt;div'));
  assert.ok(!rendered.notes.some((n) => n.includes('script')), 'nothing was stripped');
}

{
  // Scripts are the exception: the preview frame shares an origin with the
  // editor, so author JavaScript is left out and the omission is reported.
  const rendered = preview.renderQuestion({
    question: 'Q',
    subquestion: '<div class="alert">Hi<script>parent.location="/gone"</script></div>',
    fields: [],
  });
  assert.ok(rendered.html.includes('<div class="alert">Hi</div>'));
  assert.ok(!rendered.html.includes('<script'));
  assert.ok(rendered.notes.some((n) => n.includes('script')));

  const handler = preview.sanitizeHtml('<div onclick="steal()" class="a">x</div>');
  assert.strictEqual(handler, '<div class="a">x</div>');
  assert.strictEqual(preview.sanitizeHtml('<a href="javascript:evil()">x</a>'), '<a href="">x</a>');
}

// --- Mako widgets ------------------------------------------------------------

const WIDGET_BLOCKS = [
  {
    data: {
      objects: [
        { my_attachment: 'ALDocument.using(title="Motion to Dismiss", filename="motion", enabled=True)' },
        { instructions: 'ALDocument.using(title="Next steps", filename="next_steps", enabled=True)' },
      ],
    },
  },
  {
    data: {
      objects: [{
        al_user_bundle: 'ALDocumentBundle.using(elements=[my_attachment, instructions], filename="motion", title="All forms to download for your records", enabled=True)',
      }],
    },
  },
  {
    data: {
      template: 'what_happens_next',
      subject: 'What happens next?',
      content: 'The court will **mail** you a notice.',
    },
  },
];

{
  const context = preview.buildInterviewContext(WIDGET_BLOCKS);
  assert.deepStrictEqual(context.bundles.al_user_bundle, {
    title: 'All forms to download for your records',
    filename: 'motion',
    elements: ['my_attachment', 'instructions'],
  });
  assert.strictEqual(context.documents.my_attachment.title, 'Motion to Dismiss');
  assert.strictEqual(context.templates.what_happens_next.subject, 'What happens next?');

  // A bundle written across several lines parses the same way.
  const wrapped = preview.buildInterviewContext([{
    data: {
      objects: [{
        al_court_bundle: 'ALDocumentBundle.using(elements=[\n  my_attachment\n  ],\n  filename="motion",\n  title="All forms to deliver to court"\n  )',
      }],
    },
  }]);
  assert.deepStrictEqual(wrapped.bundles.al_court_bundle.elements, ['my_attachment']);
  assert.strictEqual(wrapped.bundles.al_court_bundle.title, 'All forms to deliver to court');
}

{
  // download_list_html() lists this interview's own documents when it can.
  const context = preview.buildInterviewContext(WIDGET_BLOCKS);
  const rendered = preview.renderQuestion({
    question: 'All done',
    subquestion: '${ al_user_bundle.download_list_html() }',
    fields: [],
  }, { interview: context });
  const html = rendered.html;

  assert.ok(html.includes('class="container al_table al_doc_table"'));
  assert.ok(html.includes('al_doc_title">Motion to Dismiss<'));
  assert.ok(html.includes('al_doc_title">Next steps<'));
  assert.ok(html.includes('al_view al_button'), 'each row has a View button');
  assert.ok(html.includes('al_download al_button'));
  assert.ok(html.includes('al_zip al_button'), 'the zip row is included by default');
  assert.ok(html.includes('al_doc_title">All forms to download for your records<'));
  assert.ok(!rendered.notes.some((n) => n.includes('stand-in rows')),
    'nothing was invented, so nothing is flagged');
  assert.ok(!html.includes('<p><div'), 'a block widget is not wrapped in a paragraph');
}

{
  // With no objects: block to read, two obvious stand-ins.
  const rendered = preview.renderQuestion({
    question: 'All done',
    subquestion: '${ al_user_bundle.download_list_html(view=False, include_zip=False) }',
    fields: [],
  }, {});
  assert.ok(rendered.html.includes('Your first document'));
  assert.ok(rendered.html.includes('Your second document'));
  assert.ok(!rendered.html.includes('al_view al_button'), 'view=False drops the View button');
  assert.ok(!rendered.html.includes('al_zip al_button'), 'include_zip=False drops the zip row');
  assert.ok(rendered.notes.some((n) => n.includes('stand-in rows')));
}

{
  // collapse_template() uses the named template block's own subject and content.
  const context = preview.buildInterviewContext(WIDGET_BLOCKS);
  const rendered = preview.renderQuestion({
    question: 'All done',
    subquestion: '${ collapse_template(what_happens_next) }',
    fields: [],
  }, { interview: context });
  const html = rendered.html;

  assert.ok(html.includes('class="al_collapse_template"'));
  assert.ok(html.includes('<span class="subject">What happens next?</span>'));
  assert.ok(html.includes('The court will <strong>mail</strong> you a notice.'));
  assert.ok(html.includes('card card-body pb-1 bg-light'));
  assert.ok(html.includes('class="collapsed al_toggle"'), 'collapsed is the default');
  assert.ok(!rendered.notes.some((n) => n.includes('filler text')));

  const open = preview.renderQuestion({
    question: 'All done',
    subquestion: '${ collapse_template(what_happens_next, collapsed=False, classname="bg-primary") }',
    fields: [],
  }, { interview: context });
  assert.ok(open.html.includes('class="collapse show"'));
  assert.ok(open.html.includes('card card-body pb-1 bg-primary'));
}

{
  // Which caret shows is decided entirely in CSS, so the page must carry those
  // rules itself: without them both carets draw at once.
  const doc = preview.buildDocument({
    question: 'All done',
    subquestion: '${ collapse_template(anything) }',
    fields: [],
  }, {});
  assert.ok(doc.includes('.al_collapse_template a.collapsed .pdcaretopen { display: none; }'));
  assert.ok(doc.includes('.al_collapse_template a.collapsed .pdcaretclosed { display: inline; }'));
  assert.ok(doc.includes('.al_collapse_template a span.pdcaretopen { display: inline; }'));
  assert.ok(doc.includes('.al_collapse_template a span.pdcaretclosed { display: none; }'));
}

{
  // An unknown template still shows the shape of the widget, with filler.
  const rendered = preview.renderQuestion({
    question: 'All done',
    subquestion: '${ collapse_template(some_other_template) }',
    fields: [],
  }, {});
  assert.ok(rendered.html.includes('<span class="subject">Some other template</span>'));
  assert.ok(rendered.html.includes('Lorem ipsum'));
  assert.ok(rendered.notes.some((n) => n.includes('filler text')));
}

{
  // as_pdf() gets Docassemble's stacked-paper thumbnail, with a placeholder page.
  const rendered = preview.renderQuestion({
    question: 'All done',
    subquestion: '${ al_user_bundle.as_pdf() }',
    fields: [],
  }, { interview: preview.buildInterviewContext(WIDGET_BLOCKS) });
  assert.ok(rendered.html.includes('class="da-paper-stack"'));
  assert.strictEqual((rendered.html.match(/class="da-paper"/g) || []).length, 3);
  assert.ok(rendered.html.includes('alt="Thumbnail image of document"'));
  assert.ok(rendered.html.includes('data:image/svg+xml'));
  assert.ok(rendered.html.includes('title="All forms to download for your records"'));
  assert.ok(rendered.notes.some((n) => n.includes('thumbnail is a stand-in')));
}

{
  // send_button_html() has no interesting options, so it passes straight through.
  const rendered = preview.renderQuestion({
    question: 'All done',
    subquestion: '${ al_user_bundle.send_button_html() }',
    fields: [],
  }, {});
  const html = rendered.html;
  assert.ok(html.includes('class="al_send_bundle al_send_section_alone'));
  assert.ok(html.includes('Get a copy of the documents in email'));
  assert.ok(html.includes('al_wants_editable'));
  assert.ok(html.includes('type="email"'));
  assert.ok(html.includes('al_send_email_button'));

  const noCheckbox = preview.renderQuestion({
    question: 'All done',
    subquestion: '${ al_user_bundle.send_button_html(show_editable_checkbox=False) }',
    fields: [],
  }, {});
  assert.ok(!noCheckbox.html.includes('al_wants_editable'));
}

{
  // A call spread over several lines is still recognised as one expression.
  const rendered = preview.renderQuestion({
    question: 'All done',
    subquestion: '${ al_user_bundle.download_list_html(\n    key="final",\n    include_zip=False\n) }',
    fields: [],
  }, {});
  assert.ok(rendered.html.includes('al_doc_table'));
  assert.ok(!rendered.html.includes('dapv-mako'), 'it did not fall back to showing the code');
}

{
  // action_button_html() draws the button, with the label it will really carry.
  const rendered = preview.renderQuestion({
    question: 'All done',
    subquestion: '${ action_button_html(url_action("review"), label=word("Review your answers"), icon="pencil", color="secondary", size="md") }',
    fields: [],
  }, {});
  const html = rendered.html;

  assert.ok(html.includes('Review your answers</a>'), 'word() is unwrapped to its phrase');
  assert.ok(!html.includes('word('), 'the translation call itself is not shown');
  assert.ok(html.includes('class="btn btn-secondary btn-darevisit"'), 'size md drops the size class');
  assert.ok(html.includes('<i class="fa-solid fa-pencil"></i>'));
  assert.ok(html.includes('href="#"'), 'the preview never navigates');

  const defaults = preview.renderQuestion({
    question: 'All done',
    subquestion: 'Or ${ action_button_html(url_ask(["x"])) } inline.',
    fields: [],
  }, {});
  assert.ok(defaults.html.includes('class="btn btn-sm btn-success btn-darevisit">Edit</a>'),
    "Docassemble's own defaults: small, success, labelled Edit");
  assert.ok(defaults.html.includes('<p>Or <a '), 'an inline button stays inside its paragraph');

  const exotic = preview.renderQuestion({
    question: 'All done',
    subquestion: '${ action_button_html("#", label="Go", color="chartreuse", size="enormous", new_window=True, block=True) }',
    fields: [],
  }, {});
  assert.ok(exotic.html.includes('btn-dark'), 'an unknown colour falls back to dark, as Docassemble does');
  assert.ok(exotic.html.includes('btn-sm btn-block'), 'an unknown size falls back to sm');
  assert.ok(exotic.html.includes('target="_blank"'));
}

// --- :icon: markup -----------------------------------------------------------

{
  // filter.get_icon_html: a bare name takes the default solid prefix, and
  // fas-/far-/fab- choose the style.
  assert.strictEqual(preview.applyIconMarkup('a :house: b'),
    'a <i class="fa-solid fa-house"></i> b');
  assert.strictEqual(preview.applyIconMarkup(':far-fa-circle:'),
    '<i class="fa-regular fa-circle"></i>');
  assert.strictEqual(preview.applyIconMarkup(':fab-fa-github:'),
    '<i class="fa-brands fa-github"></i>');
  assert.strictEqual(preview.applyIconMarkup(':fas-fa-star:'),
    '<i class="fa-solid fa-star"></i>');

  // Things that merely contain colons are left alone, including anything
  // inside a tag, so URLs and class lists cannot be mangled.
  assert.strictEqual(preview.applyIconMarkup('https://x.test'), 'https://x.test');
  assert.strictEqual(preview.applyIconMarkup('at 12:30:45'), 'at 12:30:45');
  assert.strictEqual(preview.applyIconMarkup(':a:'), ':a:', 'a name needs two characters');
  assert.strictEqual(preview.applyIconMarkup('<a href="x:yz:w">t</a>'), '<a href="x:yz:w">t</a>');

  const rendered = preview.renderQuestion({
    question: 'Ready :circle-check:',
    subquestion: 'Press :pencil: to change an answer.',
    fields: [{ label: 'Sign here :pen-nib:', field: 'sig' }],
  }, {});
  assert.ok(rendered.html.includes('<h1 class="h3" id="daMainQuestion">Ready <i class="fa-solid fa-circle-check"></i></h1>'));
  assert.ok(rendered.html.includes('Press <i class="fa-solid fa-pencil"></i> to change'));
  assert.ok(rendered.html.includes('Sign here <i class="fa-solid fa-pen-nib"></i>'));
}

{
  // Anything we do not have a widget for still shows as readable code.
  const rendered = preview.renderQuestion({
    question: 'Hello ${ users[0] }',
    subquestion: '${ some_other_function() }',
    fields: [],
  }, {});
  assert.ok(rendered.html.includes('dapv-mako'));
  assert.ok(rendered.html.includes('some_other_function()'));
}

// --- review: screens ---------------------------------------------------------

const REVIEW_BLOCK = {
  id: 'review answers',
  question: 'Review your answers',
  subquestion: 'Check anything you want to change.',
  review: [
    { Edit: 'users[0].name.first', button: '**Your name**: ${ users[0] }' },
    { note: 'You can come back to this screen later.' },
    { Edit: 'user_email', help: 'We will email your forms here.' },
    'other_parties[0].name.first',
  ],
};

{
  // renderScreen picks the review renderer from the shape of the block.
  const rendered = preview.renderScreen(REVIEW_BLOCK, {});
  const html = rendered.html;

  assert.ok(html.includes('class="form-horizontal daformreview"'));
  assert.ok(html.includes('<h1 class="h3" id="daMainQuestion">Review your answers</h1>'));

  // An item with a button: gets Docassemble's button treatment.
  assert.ok(html.includes('da-review da-review-button bg-secondary-subtle pt-2 my-2'));
  assert.ok(html.includes('da-review-action da-review-action-button'));
  assert.ok(html.includes('<i class="fa-solid fa-pencil-alt"></i>'));
  assert.ok(html.includes('<strong>Your name</strong>'));

  // A note is its own row; a bare item is a plain revisit link.
  assert.ok(html.includes('da-field-container-note da-review'));
  assert.ok(html.includes('da-form-group row da-review da-review-label'));
  assert.ok(html.includes('<a href="#" class="da-review-action">other_parties[0].name.first</a>'));

  // help: on a non-button item becomes the help row under the link.
  assert.ok(html.includes('da-review da-review-help'));
  assert.ok(html.includes('We will email your forms here.'));

  // A review screen resumes rather than continues.
  assert.ok(html.includes('>Resume</button>'));
  assert.ok(html.includes('>Undo</button>'));
  assert.strictEqual(rendered.itemCount, 4);
}

{
  // tabular: True lays the same items out as a table.
  const rendered = preview.renderScreen(
    Object.assign({}, REVIEW_BLOCK, { tabular: true }), {}
  );
  assert.ok(rendered.html.includes('<table class="da-review-tabular table table-borderless"><tbody>'));
  assert.ok(rendered.html.includes('da-review-button-tabular'));
  assert.ok(!rendered.html.includes('da-form-group row da-review da-review-label'));

  const custom = preview.renderScreen(
    Object.assign({}, REVIEW_BLOCK, { tabular: 'table table-sm' }), {}
  );
  assert.ok(custom.html.includes('<table class="da-review-tabular table table-sm">'));
}

{
  const empty = preview.renderScreen({ question: 'Review', review: [] }, {});
  assert.ok(empty.notes.some((n) => n.includes('no items yet')));

  const renamed = preview.renderScreen(
    Object.assign({}, REVIEW_BLOCK, { 'continue button label': 'Back to my forms' }), {}
  );
  assert.ok(renamed.html.includes('>Back to my forms</button>'));
}

// --- table: blocks -----------------------------------------------------------

const TABLE_BLOCK = {
  table: 'users.table',
  rows: 'users',
  columns: [
    { Name: 'row_item.name.full()' },
    { Address: 'row_item.address.on_one_line()' },
    { Phone: 'row_item.phone_number' },
  ],
  edit: ['name.first', 'address.address'],
  'delete buttons': true,
  confirm: true,
};

{
  const html = preview.renderTable(TABLE_BLOCK, {});

  assert.ok(html.includes('<div class="table-responsive"><table class="table table-striped">'));
  assert.ok(html.includes('<th>Name</th><th>Address</th><th>Phone</th><th>Actions</th>'));

  // Two rows, with values chosen from what each column is for.
  assert.strictEqual((html.match(/<tr>/g) || []).length, 3, 'a header row and two body rows');
  assert.ok(html.includes('<td>Alex Kim</td>'));
  assert.ok(html.includes('<td>Jordan Rivera</td>'));
  assert.ok(html.includes('123 Main St, Boston, MA 02114'));
  assert.ok(html.includes('(617) 555-0134'));

  // DAList.item_actions markup, including confirm-on-delete.
  assert.ok(html.includes('<i class="fa-solid fa-pencil-alt"></i> Edit'));
  assert.ok(html.includes('<i class="fa-solid fa-trash"></i> Delete'));
  assert.ok(html.includes('btn btn-sm btn-danger btn-darevisit daremovebutton'));
}

{
  // No edit or delete directive means no Actions column at all.
  const html = preview.renderTable({
    table: 'users.table',
    rows: 'users',
    columns: [{ Name: 'row_item.name.full()' }],
  }, {});
  assert.ok(!html.includes('Actions'));
  assert.ok(!html.includes('fa-trash'));

  const custom = preview.renderTable(
    Object.assign({}, TABLE_BLOCK, { 'edit header': 'Change' }), {}
  );
  assert.ok(custom.includes('<th>Change</th>'), 'edit header renames the actions column');

  const headerCell = preview.renderTable({
    table: 'x.table',
    rows: 'x',
    columns: [{ header: 'Item', cell: 'row_item.name' }],
  }, {});
  assert.ok(headerCell.includes('<th>Item</th>'));
  assert.ok(headerCell.includes('<td>Alex Kim</td>'), 'header/cell form is read too');
}

{
  // Previewing the table block itself shows the table plus its Add button.
  const rendered = preview.renderScreen(TABLE_BLOCK, {});
  assert.ok(rendered.html.includes('<code>${ users.table }</code>'));
  assert.ok(rendered.html.includes('table table-striped'));
  assert.ok(rendered.html.includes('fa-plus-circle'));
  assert.ok(rendered.notes.some((n) => n.includes('Table rows are examples')));
  assert.ok(!rendered.html.includes('daformfields'), 'a table block is not a form');
}

{
  // ${ users.table } inside a screen renders that block's table.
  const context = preview.buildInterviewContext([{ data: TABLE_BLOCK }]);
  assert.ok(context.tables['users.table']);

  const rendered = preview.renderScreen({
    question: 'Is anyone else involved?',
    subquestion: '${ users.table }\n\n${ users.add_action() }',
    fields: [],
  }, { interview: context });
  assert.ok(rendered.html.includes('<th>Address</th>'));
  assert.ok(rendered.html.includes('<td>Jordan Rivera</td>'));
  assert.ok(rendered.html.includes('btn btn-sm btn-secondary btn-darevisit">' +
    '<i class="fa-solid fa-plus-circle"></i> Add another</a>'));
  assert.ok(rendered.notes.some((n) => n.includes('Table rows are examples')));

  // An unknown table still shows the shape of one, and says so.
  const unknown = preview.renderScreen({
    question: 'Anyone else?',
    subquestion: '${ other_parties.table }',
    fields: [],
  }, {});
  assert.ok(unknown.html.includes('table table-striped'));
  assert.ok(unknown.notes.some((n) => n.includes('not in this file')));
}

{
  const labelled = preview.renderScreen({
    question: 'Anyone else?',
    subquestion: '${ users.add_action(label="Add another person", icon="user-plus", color="primary", size="md") }',
    fields: [],
  }, {});
  assert.ok(labelled.html.includes('Add another person</a>'));
  assert.ok(labelled.html.includes('fa-solid fa-user-plus'));
  assert.ok(labelled.html.includes('class="btn btn-primary btn-darevisit"'));
}

// --- markdown ----------------------------------------------------------------

{
  assert.strictEqual(preview.renderInlineMarkdown('Plain'), 'Plain');
  assert.strictEqual(preview.renderInlineMarkdown('**Bold**'), '<strong>Bold</strong>');
  assert.ok(preview.renderMarkdown('- one\n- two').includes('<ul><li>one</li><li>two</li></ul>'));
  assert.ok(preview.renderMarkdown('${ users[0] }').includes('dapv-mako'),
    'Mako expressions are shown, not evaluated');
  assert.ok(preview.renderMarkdown('% if x:').includes('dapv-mako-line'));
}

{
  // Inline markup is matched across the whole block, not line by line: a link
  // whose text wraps must still become a link.
  const wrapped = preview.renderMarkdown(
    '* [Working with \nPDFs](https://example.test/pdfs)\n* [DOCX files](https://example.test/docx)'
  );
  assert.ok(wrapped.includes('href="https://example.test/pdfs"'));
  assert.ok(wrapped.includes('href="https://example.test/docx"'));
  assert.ok(!wrapped.includes('](https'), 'no link markup is left literal');
  assert.strictEqual((wrapped.match(/<li>/g) || []).length, 2);

  const inParagraph = preview.renderMarkdown(
    'The fields should use the [Assembly Line variable\nstandard](https://example.test/labels).'
  );
  assert.ok(inParagraph.includes('href="https://example.test/labels"'));

  const acrossLines = preview.renderMarkdown('This is **bold\ntext** here.');
  assert.ok(acrossLines.includes('<strong>bold\ntext</strong>'));

  // Docassemble does not load nl2br, so a single newline is whitespace; [BR]
  // is how an author forces a break.
  const plain = preview.renderMarkdown('one\ntwo');
  assert.ok(!plain.includes('<br'), 'a bare newline is not a line break');
  assert.ok(preview.renderMarkdown('one[BR]two').includes('<br />'));

  // A blank line still ends the block.
  const twoParagraphs = preview.renderMarkdown('one\n\ntwo');
  assert.strictEqual((twoParagraphs.match(/<p>/g) || []).length, 2);

  // A continuation line must not swallow the next list item or heading.
  const mixed = preview.renderMarkdown('* one\n# Heading\n* two');
  assert.ok(mixed.includes('<h2>Heading</h2>'));
  assert.strictEqual((mixed.match(/<li>/g) || []).length, 2);
}

process.on('exit', function (code) {
  if (code === 0) console.log('editor_screen_preview.js checks passed');
});
