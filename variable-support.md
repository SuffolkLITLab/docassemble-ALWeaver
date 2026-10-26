# Expanded variable support (unreleased)

These are the contracts implemented on `feature/expanded-variable-support`.
No released minimum versions have been assigned. The name-and-address label
requires the [companion AssemblyLine patch](patches/assemblyline-name-and-address.patch); do not
publish that feature as available on an authoring server until both packages
are installed and its generated interviews have been exercised there.

| PDF label | DOCX expression | Type and supplier |
| --- | --- | --- |
| `grandchildren1_name` | `grandchildren[0]` | `ALPeopleList`; ordinary people gathering |
| `grandchildren1_name_first` | `grandchildren[0].name.first` | Text; ordinary name question |
| `users1_address_block` | `users[0].address.block()` | Address only; unchanged |
| `users1_name_and_address_block` | `users[0].address_block()` | Formatted name and address; both dependencies collected |
| `users1_service_method` | `users[0].service_method` | Baseline service question, using `al_service_methods` |
| `users1_service_address_block` | `users[0].service_address.block()` | Baseline service-address question |
| `users1_service_address_city` | `users[0].service_address.city` | Service-address component; also address, unit, state, zip, country and county |
| `service_date` | `service_date` | Date; author controls wording and event meaning |
| `trial_court_circuit` | `trial_court_circuit` | Text; authored derivation or optional fallback question |

Service addresses also accept the residential address formatting suffixes
`on_one_line`, `line_one`, `line_two`, and `city_state_zip`. County is not part
of the ordinary address screen; supply a county question if your form needs it.
Service fields alone do not establish a new custom person: a custom role needs
other person evidence (such as a name field) or an explicit declaration.
Grandchildren use the standard list model, not a family tree. Custom people
roles remain supported; a broad legal-role vocabulary is not necessary.

## Standalone addresses

In `/al/editor`, open the question library, choose **Add a person or address to
this interview**, enter `property_address`, and select **An address**. Add its
address question. This declares `property_address: ALAddress` and offers no
person-name question. If that variable is already declared, change its class
in the existing Objects block instead of declaring it twice. Remove obsolete
person questions when converting an existing person declaration.

Use `{{ property_address.city }}` or `{{ property_address.block() }}` in DOCX.
For programmatic PDF/DOCX import, declare types explicitly:

```python
generate_interview_from_path(
    "property.pdf",
    interview_overrides={"object_types": {"property_address": "ALAddress"}},
)
```

For that PDF declaration, `property_address_city`, `property_address_address`,
`property_address_unit`, `property_address_state`, `property_address_zip`,
`property_address_country`, `property_address_block`, `property_address_line_one`,
`property_address_line_two` and `property_address_on_one_line` map to address
components or methods. Dotted PDF expressions also work. This explicit type
wins over person inference. Unsupported attributes still need authored questions.
The editor can preserve and edit the generated declaration and question.
The legacy wizard does not yet offer an address-type selector.

A minimal standalone interview is [standalone-address.yml](docassemble/ALWeaver/data/questions/examples/standalone-address.yml).

## Court circuit

The output convention deliberately stays a scalar `trial_court_circuit`.
Weaver does not assume `trial_court.circuit`, convert a circuit to an integer,
or copy a provider's arbitrary attribute. The optional fallback has its own
question, so asking for another missing court detail does not overwrite a
provider's circuit. It is not suppressed by the jurisdiction's broader
`court_details` flag. A checkbox with this label remains a custom checkbox.

Authors can replace the fallback with a code block, for example
`trial_court_circuit = trial_court.circuit` **if their selected provider supplies
that attribute**. A provider using `the_court.number` needs its own mapping and
a check that the selected court is a circuit court. Preserve provider formatting;
use `""` when circuit is inapplicable. Weaver does not install these mappings.

## Service recipients and event scope

`service_recipients` is a recipe convention, not an automatically gathered list
of new people. [service-recipients.yml](docassemble/ALWeaver/data/questions/examples/service-recipients.yml)
selects existing objects and collects different methods and addresses for them.
The list members retain their identity; changing a recipient changes the same
person in the party list.

For one event with a shared method/date, authors can ask `service_method` and
`service_date` once. For different recipient information, use per-person
attributes as the example does. For multiple events, use event-specific fields
or an authored event model; do not silently reuse one date or overwrite a
person's earlier service information. Delivery and service are not universal
aliases: existing `delivery_parties` and `delivery_date` keep their meanings.

`service_method+by_mail` is generic [choice grouping](docs/option_groups.md).
`by_mail` is an author-defined stored choice, not a promised match for
AssemblyLine's baseline `al_service_methods`. Configure those choices for the
interview and jurisdiction. The example's choices are illustrative.

## Existing rows, choices, and quantity controls

`other_case_1_docket`, `other_case_1_court`, `other_case_2_docket`, and
`other_case_2_court` form `other_cases[0]` and `other_cases[1]`. The modern import
path generates collection questions, fixed PDF slots, and overflow handling.
A single repeated scalar suffix is insufficient evidence of a row family.
This recognizes labels, not arbitrary visual table layouts. DOCX authors can
use native Jinja table loops for unbounded rows; fixed indexed references remain
fixed slots. Do not use the old proposed `table0+column` syntax: `+` separates
a variable and a choice option. Turn off automatic normalization for `+` labels.

The legacy wizard calls `add_fields_from_file()` directly and builds its own
objects list; it does not invoke modern row-family consolidation. That parity
gap remains open, so these checks alone do not justify closing #96. Choice
grouping is in the shared field importer used by both routes (#893).

| Intended people-list behavior | Declaration |
| --- | --- |
| Ask whether there are any | `ALPeopleList` |
| At least one | `ALPeopleList.using(there_are_any=True)` |
| Ask how many | `ALPeopleList.using(ask_number=True)` |
| Exactly N | `ALPeopleList.using(ask_number=True, target_number=N)` |

## Nested representation and release gates

Nested attorney/lawyer inference remains outside this change. Authors can
explicitly declare `users[i].lawyer: ALIndividual` in source, with their own
representation and name questions. Neither `.lawyer` nor `.attorney` is an
automatic alias, and no attorney is initialized on every person. Shared counsel
should be an authored reference to an existing person.

The examples and representative PDF/DOCX attachments were exercised on localhost,
including address review edits (see [validation](validation/expanded-variable-validation.md)).
Before release, finish the confidential-address browser matrix, empty and
multiple-person list cases, and row overflow. Publish actual package minimums and
update the AssemblyLine-docs field reference and generated API docs after the
runtime release. Issue closures and release publication are not part of this
branch; #670 in particular still depends on installing the companion runtime fix.


## Existing-template regression audit

The [corpus snapshot comparison](validation/variable-recognition-corpus.json)
records changes against the branch's base commit. Reproduce the snapshots with
`scripts/variable_recognition_corpus.py --checkout CHECKOUT --corpus CORPUS --output OUTPUT`.
The audit uses the actual PDF/DOCX field importer, people recognition, row
consolidation, gathering triggers and object inference. It does not execute
existing authored interviews or render their attachments.

The corpus exposed a singleton/list ambiguity in older DOCX templates: a bare
`client` reference alongside `client.address` is still one person. Bare name
references now preserve that singleton when dotted attributes exist and there
are no indexed references. Bare collections without dotted evidence and indexed
collections keep their list behavior.
