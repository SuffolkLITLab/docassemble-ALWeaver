'use strict';

const assert = require('assert');
// The report module renders its screens with the preview renderer, which it
// picks up off the global the way the editor page loads it: preview first.
require('./data/static/editor_screen_preview.js');
const report = require('./data/static/editor_interview_report.js');

const blocks = [
  { id: 'b1', type: 'question', variable: 'user_understands', title: 'Before you start',
    data: { question: 'Before you start', subquestion: 'This takes 10 minutes.',
            fields: [{ label: 'I understand', field: 'user_understands', datatype: 'yesno' }] } },
  { id: 'b2', type: 'question', variable: 'users[0].name.first', title: 'What is your name?',
    data: { question: 'What is your name?', fields: [{ code: 'users[0].name_fields()' }] } },
  { id: 'b3', type: 'question', variable: 'has_children', title: 'Do you have children?',
    data: { question: 'Do you have children?', yesno: 'has_children' } },
  { id: 'b4', type: 'question', variable: 'children[0].name.first', title: 'Tell us about your child',
    data: { question: 'Tell us about your child',
            fields: [{ label: 'Name', field: 'children[0].name.first' }] } },
  { id: 'b5', type: 'question', variable: 'children[0].school', title: 'Where does this child go to school?',
    sourceFile: 'family.yml',
    data: { question: 'Where does this child go to school?',
            fields: [{ label: 'School', field: 'children[0].school' }] } },
  { id: 'b6', type: 'objects',
    data: { objects: [{ users: 'ALPeopleList.using(there_are_any=True)' },
                      { children: 'ALPeopleList' },
                      { exhibits: 'DAList.using(object_type=DAObject)' }] } },
  { id: 'b7', type: 'code', variable: 'children[i].complete',
    data: { code: 'children[i].name.first\nchildren[i].address.address\nchildren[i].school\nchildren[i].complete = True' } },
  { id: 'b8', type: 'sections',
    data: { sections: [{ intro_section: 'Getting started' }, { family_section: 'Your family' }] } },
];

const steps = [
  { kind: 'section', value: 'intro_section' },
  { kind: 'screen', invoke: 'user_understands', summary: 'user_understands' },
  { kind: 'progress', value: '25', summary: 'Set progress to 25%' },
  { kind: 'screen', invoke: 'users[0].name.first', summary: 'users[0].name.first' },
  { kind: 'section', value: 'family_section' },
  { kind: 'screen', invoke: 'has_children', summary: 'has_children' },
  { kind: 'condition', condition: 'has_children', has_else: true,
    children: [
      { kind: 'gather', invoke: 'children.gather()', summary: 'Gather children list' },
      { kind: 'screen', invoke: 'children[0].name.first', summary: 'children[0].name.first' },
    ],
    else_children: [
      { kind: 'function', invoke: 'set_progress(90)', summary: 'set_progress(90)' },
    ] },
  { kind: 'screen', invoke: 'screen_from_an_include', summary: 'screen_from_an_include' },
  { kind: 'screen', invoke: 'trial_court', summary: 'trial_court' },
  { kind: 'function', invoke: 'set_parts(subtitle="x")', summary: 'set_parts(subtitle="x")' },
];

const blockMap = report.buildBlockMap(blocks);

// --- Flowchart --------------------------------------------------------------

{
  const src = report.buildMermaidSource(steps, {
    blockMap: blockMap,
    objects: report.objectDeclarations(blocks),
    sections: report.sectionLabels(blocks),
  });

  // A node says what the screen says, not just what variable triggers it.
  assert.ok(src.includes('"Before you start<br><small>user_understands</small>"'),
    'a screen node is labelled with its question, with the variable underneath');
  assert.ok(src.includes('Do you have children?<br>'), 'every screen node carries its title');
  assert.ok(!/N\d+\["user_understands"\]/.test(src), 'no node is labelled by the variable alone');

  // Sections group the nodes they contain.
  assert.ok(/subgraph S1\["Getting started"\]/.test(src),
    'a section opens a subgraph, titled by its label rather than its key');
  assert.ok(/subgraph S2\["Your family"\]/.test(src), 'the next section opens the next subgraph');
  const gettingStarted = src.slice(src.indexOf('subgraph S1'), src.indexOf('subgraph S2'));
  assert.ok(gettingStarted.includes('Before you start'), 'the section holds its own screens');
  assert.ok(!gettingStarted.includes('Do you have children?'),
    'a screen after the next section: line belongs to that section');

  // Progress is an annotation on the arrow, never a node of its own.
  assert.ok(/-->\|"25%"\| /.test(src), 'a progress change labels the arrow where it happens');
  assert.ok(!/N\d+\("?25%/.test(src), 'a progress change is not drawn as a node');

  // Shapes carry their usual flowchart meaning.
  assert.ok(/N\d+\{"has_children"\}/.test(src), 'a condition is a diamond');
  assert.ok(/N\d+\[\["For every child<br>/.test(src), 'a list gather is a subroutine box');
  assert.ok(/N\d+\{\{"set_progress\(90\)"\}\}/.test(src), 'code that runs is a hexagon');
  assert.ok(src.includes('N0(["Start"])') && src.includes('NZ(["Interview complete"])'),
    'the walk has a start and a finish');

  // Both sides of a branch are drawn, and both rejoin what follows.
  assert.ok(/-->\|"yes"\| /.test(src) && /-->\|"no"\| /.test(src), 'a branch labels both arrows');

  // A screen this file cannot see is still on the chart, drawn as missing.
  assert.ok(src.includes('classDef missing'), 'a screen from an included file is styled as missing');
}

{
  // Nothing to walk still produces a chart that parses.
  const src = report.buildMermaidSource([], {});
  assert.ok(src.startsWith('flowchart TD'));
  assert.ok(src.includes('N0 --> NZ'), 'an empty interview goes straight from start to finish');
}

// --- Parts ------------------------------------------------------------------

{
  const parts = report.splitIntoParts(steps, report.sectionLabels(blocks));
  assert.deepStrictEqual(parts.map((p) => p.title), ['Getting started', 'Your family']);
  assert.strictEqual(parts[0].steps.length, 3, 'the section: line itself is not a step in the part');
}

{
  // A file with no sections is one unnamed part rather than none.
  const parts = report.splitIntoParts([{ kind: 'screen', invoke: 'x' }]);
  assert.strictEqual(parts.length, 1);
  assert.strictEqual(parts[0].title, null);
}

// --- What a list gather asks -------------------------------------------------

{
  const objects = report.objectDeclarations(blocks);
  assert.deepStrictEqual(objects.users, { className: 'ALPeopleList', args: 'there_are_any=True' });

  // Followed to the code block that defines the complete attribute.
  const traced = report.describeGather({ kind: 'gather', invoke: 'children.gather()' },
    { blockMap: blockMap, objects: objects });
  assert.strictEqual(traced.source, 'complete-attribute');
  assert.deepStrictEqual(traced.attributes.map((a) => a.head), ['name', 'address', 'school'],
    'the loop asks what the complete attribute asks, in that order');
  assert.strictEqual(traced.noun, 'child');

  // Nothing defines one, so AssemblyLine's own default for a list of people.
  const fallback = report.describeGather({ kind: 'gather', invoke: 'users.gather()' },
    { blockMap: blockMap, objects: objects });
  assert.strictEqual(fallback.source, 'assembly-line-default');
  assert.deepStrictEqual(fallback.attributes.map((a) => a.head), ['name']);

  // A list of something other than people gets no invented answer.
  const other = report.describeGather({ kind: 'gather', invoke: 'exhibits.gather()' },
    { blockMap: blockMap, objects: objects });
  assert.strictEqual(other.source, 'unknown');
  assert.deepStrictEqual(other.attributes, []);

  // The call itself can name the attribute.
  const named = report.describeGather(
    { kind: 'gather', invoke: "children.gather(complete_attribute='complete')" },
    { blockMap: blockMap, objects: objects });
  assert.strictEqual(named.source, 'complete-attribute');

  // List bookkeeping is not something the reader is asked for.
  const attrs = report.attributesFromCode(
    'x[i].name.first\nx[i].there_is_another\nx[i].complete = True\nx[i].address.address', 'x');
  assert.deepStrictEqual(attrs.map((a) => a.head), ['name', 'address']);
}

// --- Sections are named by their label, not their key ------------------------

{
  const labels = report.sectionLabels(blocks);
  assert.strictEqual(labels.intro_section, 'Getting started');

  const parts = report.splitIntoParts(steps, labels);
  assert.deepStrictEqual(parts.map((p) => p.title), ['Getting started', 'Your family'],
    'nav.set_section("intro_section") is reported as the label a reader sees');

  // A subtitle set with set_parts() is already prose; it stays as written.
  assert.deepStrictEqual(
    report.splitIntoParts([{ kind: 'section', value: 'Your money' }], labels).map((p) => p.title),
    ['Your money']);

  // Nested sections, and a bare string entry.
  const nested = report.sectionLabels([{ data: { sections: ['plain', { top: [{ sub: 'Sub' }] }] } }]);
  assert.strictEqual(nested.sub, 'Sub');
  assert.strictEqual(nested.plain, 'plain');

  // AssemblyLine keeps the same shape under a different key.
  const alNav = report.sectionLabels([
    { data: { 'variable name': 'al_nav_sections', data: [{ money: 'Your money', hidden: false }] } },
  ]);
  assert.strictEqual(alNav.money, 'Your money');
}

// --- Screens AssemblyLine supplies -------------------------------------------

{
  const name = report.assemblyLineStandIn('users[i].name.first');
  assert.strictEqual(name.title, 'Name of each user');
  assert.strictEqual(name.block.data.fields[0].code, 'users[i].name_fields()');

  const address = report.assemblyLineStandIn('other_parties[0].address.address');
  assert.strictEqual(address.title, 'Address of the other party');
  assert.ok(/address_fields\(/.test(address.block.data.fields[0].code));

  // Every trial_court variable belongs to AssemblyLine's court question,
  // including its address -- which must not be read as a person's address.
  ['trial_court', 'trial_court_name', 'trial_court_address.address'].forEach((variable) => {
    assert.strictEqual(report.assemblyLineStandIn(variable).title, 'Choose a court', variable);
  });
  assert.strictEqual(
    report.assemblyLineStandIn('trial_court_address.address').block.data.fields[0].Name,
    'trial_court_name');

  assert.strictEqual(report.assemblyLineStandIn('some_interview_variable'), null,
    'nothing is invented for a variable AssemblyLine does not answer');
}

// --- Screens read out of an installed package --------------------------------

{
  // What /api/package-file returns for AssemblyLine's generic questions.
  const packaged = [
    { id: 'p1', type: 'question', variable: 'x.name.first',
      sourceFile: 'docassemble.AssemblyLine:ql_baseline.yml', sourceLabel: 'AssemblyLine',
      data: { 'generic object': 'ALIndividual', sets: ['x.name.first', 'x.name.last'],
              question: "What is ${x.object_possessive('name')}?",
              fields: [{ code: 'x.name_fields()' }] } },
    { id: 'p2', type: 'question', variable: 'x.address.address',
      sourceFile: 'docassemble.AssemblyLine:ql_baseline.yml', sourceLabel: 'AssemblyLine',
      data: { 'generic object': 'ALIndividual', sets: ['x.address.address', 'x.address.city'],
              question: "What is ${ x.possessive('address') }?",
              fields: [{ code: 'x.address_fields()' }] } },
    { id: 'p3', type: 'question', variable: 'trial_court_name', title: 'What court is your case in?',
      sourceFile: 'docassemble.AssemblyLine:ql_baseline.yml', sourceLabel: 'AssemblyLine',
      data: { question: 'What court is your case in?',
              fields: [{ 'Name': 'trial_court_name' }, { 'Address': 'trial_court_address.address' }] } },
    { id: 'p4', type: 'code',
      sourceFile: 'docassemble.AssemblyLine:ql_baseline.yml', sourceLabel: 'AssemblyLine',
      data: { 'depends on': ['trial_court_name', 'trial_court_address.address'],
              code: '# a comment first, so nothing is read as the variable\ntrial_court = ALCourt("trial_court")' } },
  ];
  const packagedMap = report.buildBlockMap(packaged);

  // One generic block answers every subject, rewritten for the one asked for.
  const generic = report.findGenericBlock('other_parties[0].address.address', packagedMap);
  assert.ok(generic, 'a generic question answers a variable it was not written for');
  assert.strictEqual(generic.genericSubject, 'other_parties[0]');
  assert.strictEqual(generic.data.question, "What is ${ other_parties[0].possessive('address') }?",
    'the subject is put back into the wording');
  assert.strictEqual(generic.data.fields[0].code, 'other_parties[0].address_fields()');
  assert.deepStrictEqual(generic.data.sets, ['other_parties[0].address.address', 'other_parties[0].address.city']);
  assert.strictEqual(packaged[1].data.question, "What is ${ x.possessive('address') }?",
    'the package block itself is left alone');

  // Mako wording makes a poor name in a contents list; the variable does better.
  assert.strictEqual(report.screenTitle({ invoke: 'other_parties[0].address.address' }, packagedMap).title,
    'Address of the other party');
  assert.strictEqual(report.screenTitle({ invoke: 'users[i].name.first' }, packagedMap).title,
    'Name of each user');

  // A variable that only code assembles resolves to the screen it depends on.
  const court = report.screenTitle({ invoke: 'trial_court' }, packagedMap);
  assert.strictEqual(court.title, 'What court is your case in?',
    "code that builds trial_court is followed to the question it needs");
  assert.strictEqual(court.block.id, 'p3');

  // Code assignments never shadow a question that asks for the same variable.
  const shadowed = report.buildBlockMap([
    { id: 'code', type: 'code', data: { code: 'has_children = True' } },
    { id: 'question', type: 'question', variable: 'has_children',
      data: { question: 'Do you have children?' } },
  ]);
  assert.strictEqual(report.findBlock('has_children', shadowed).id, 'question');

  // The interview's own screen wins over the package's.
  const merged = report.buildBlockMap([
    { id: 'mine', type: 'question', variable: 'users[0].address.address',
      data: { question: 'Where do you live?' } },
  ].concat(packaged));
  assert.strictEqual(report.findBlock('users[0].address.address', merged).id, 'mine',
    'the open file is read before the packages it includes');

  // Rendered, the package screen is badged by its package.
  const html = report.buildReport(
    [{ kind: 'screen', invoke: 'other_parties[0].address.address' }], packaged, {});
  assert.ok(html.includes('>AssemblyLine</span>'), 'a package screen says where it came from');
  assert.ok(html.includes("other_parties[0].possessive("), 'and is drawn with the subject filled in');
}

// --- Screen titles ----------------------------------------------------------

{
  const found = report.screenTitle({ invoke: 'users[0].name.first' }, blockMap);
  assert.strictEqual(found.title, 'What is your name?');
  assert.strictEqual(found.variable, 'users[0].name.first');
  assert.ok(found.block, 'the block behind the variable is found');

  const missing = report.screenTitle({ invoke: 'screen_from_an_include' }, blockMap);
  assert.strictEqual(missing.block, null);
  assert.strictEqual(missing.title, 'Screen from an include', 'an unknown screen is titled by its name');
}

// --- The document ------------------------------------------------------------

{
  const html = report.buildReport(steps, blocks, {
    title: 'demo — Interview flow report',
    origin: 'https://da.example.org',
    extraCss: ['/packagestatic/docassemble.AssemblyLine/styles.css'],
    continueLabel: 'Next',
  });

  // The screens are drawn by the preview renderer, in the markup Docassemble
  // keys its own stylesheets to.
  assert.ok(html.includes('<body class="dabody">'), 'the page is a Docassemble body');
  assert.ok(html.includes('<div id="dabody">'), 'the screens sit inside a #dabody');
  assert.ok(html.includes('<div class="container"><div class="row tab-content">'),
    'each screen keeps the container/row chain');
  assert.ok(html.includes('id="daquestion"'), 'the question markup itself is preserved');
  assert.ok(html.includes('>Next<'), 'the interview\'s own continue label is used');

  // Every stylesheet is absolute: a blob: URL cannot resolve a rooted path.
  assert.ok(html.includes('href="https://da.example.org/static/bootstrap/css/bootstrap.min.css"'));
  assert.ok(html.includes('href="https://da.example.org/static/app/bundle.css"'));
  assert.ok(html.includes('href="https://da.example.org/packagestatic/docassemble.AssemblyLine/styles.css"'));
  assert.ok(!/href="\/static/.test(html), 'no stylesheet is left root-relative');
  assert.ok(!/src="\/static/.test(html), 'no script is left root-relative');

  // Field ids are per screen, so a label on one screen cannot answer another.
  assert.ok(html.includes('id="s1_dapv_field_0"') && html.includes('id="s2_dapv_field_0"'),
    'each screen numbers its fields under its own prefix');
  assert.ok(!/id="dapv_field_/.test(html), 'no unprefixed field id survives');

  // Contents, numbering and the flowchart.
  assert.ok(html.includes('href="#alwr-screen-1"') && html.includes('id="alwr-screen-1"'),
    'the contents link to the screens');
  assert.ok(html.includes('>Getting started</a>'), 'sections are listed in the contents');
  assert.ok(html.indexOf('alwr-toc') < html.indexOf('alwr-flow'),
    'contents come before the flowchart, so page one of a printout is not blank');
  assert.ok(html.includes('<pre class="mermaid">'), 'the flowchart is on the page');
  assert.ok(html.includes('alwr-mermaid-fallback'), 'the source shows if Mermaid cannot load');
  assert.ok(html.includes('@media print'), 'the document has print rules');
  assert.ok(html.includes('break-before:page'), 'sections start a new printed page');

  // The screen this interview cannot see is reported rather than skipped.
  assert.ok(html.includes('alwr-screen-missing'));
  assert.ok(html.includes('No screen for this was found'));

  // A screen from an included file says which file it came from.
  assert.ok(html.includes('>family.yml</span>'), 'an included screen is badged with its file');

  // AssemblyLine's own screens are drawn rather than left as a hole.
  assert.ok(html.includes('Choose a court'), 'the court question is reproduced');
  assert.ok(html.includes('>Suite<') && html.includes('>Postal code<'),
    'with the fields AssemblyLine asks for');
  assert.ok(html.includes('Address of each child'), "and the address question in the gather loop");
  assert.ok(html.includes('>AssemblyLine default</span>'),
    'the built-in copies are badged apart from a screen read out of the package');

  // Sections are titled the way the navigation titles them.
  assert.ok(html.includes('>Getting started</h2>') || html.includes('Getting started</h2>'),
    'the section heading is the label, not the key');
  assert.ok(!html.includes('intro_section'), 'the section key is not shown anywhere');

  // The list loop says what it asks for, and shows those screens.
  assert.ok(html.includes('For every child'), 'the loop names what it repeats over');
  assert.ok(html.includes('asks for name, address and school'),
    'the loop lists the attributes it gathers');
  assert.ok(!html.includes('Ask the screens above once for each'), 'the old wrong description is gone');

  // Nothing in the report explains the report to its reader.
  assert.ok(!html.includes('Mako expressions'), 'no note explaining how the preview works');
  assert.ok(!html.includes('Preview notes'), 'no author-facing preview notes');
  const screensSection = html.slice(html.indexOf('<div id="dabody">'));
  assert.ok(!screensSection.includes('set_parts'),
    'code that runs between screens is charted but not written out among the screens');
}

{
  // An interview with no order block still gets a readable page.
  const html = report.buildReport([], [], {});
  assert.ok(html.includes('no screens in its interview order yet'));
}

// --- Asset URLs --------------------------------------------------------------

{
  const abs = report.absoluteUrl;
  assert.strictEqual(abs('/static/x.css', 'https://da.example.org'), 'https://da.example.org/static/x.css');
  assert.strictEqual(abs('/static/x.css', 'https://da.example.org/'), 'https://da.example.org/static/x.css');
  assert.strictEqual(abs('https://cdn/x.js', 'https://da.example.org'), 'https://cdn/x.js');
  assert.strictEqual(abs('//cdn/x.js', 'https://da.example.org'), '//cdn/x.js');
  assert.strictEqual(abs('/static/x.css', ''), '/static/x.css');
}

console.log('editor_interview_report.js: all assertions passed');
