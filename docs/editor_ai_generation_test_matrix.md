# `/al/editor` AI generation test matrix

Last executed: 2026-08-12 against the local Docker server after installing the
working tree with `dainstall`.

## Scope and evaluation method

Thirteen live `gpt-5-nano` queries used the OpenAI credentials configured on
the local Docassemble server:

- eight full-screen generations, including the initial smoke test and final
  UI apply/save test; and
- five fields-only generations.

The tests did more than check status codes. Each output was checked for:

- relevance to the requested legal-interview topic;
- substantive labels and Python-safe, unique variable names;
- appropriate datatypes selected only from the supplied allowlist;
- at least two choices for radio, dropdown, checkbox, or multiselect fields;
- one to seven usable fields;
- required topic vocabulary or concepts;
- server-reported model and DAYamlChecker-validated candidate YAML;
- no Playground write before the developer presses Save;
- Save-button enablement after applying the generated screen; and
- preservation of unrelated YAML comments and literal scalar content after
  saving through the graphical editor.

## Results

| Generation | Mode | Sanity result | Notes |
| --- | --- | --- | --- |
| Contact information smoke test | Screen | Pass | Full name, email, international phone |
| Mailing address | Screen | Pass | Street, city, state, ZIP |
| Incident date/time/location | Screen | Pass | Correct `date`, `time`, and text datatypes |
| Monthly income | Screen | Pass | Currency fields plus choice-backed frequency |
| Massachusetts residence | Screen | Pass | One clear `yesno` field |
| Court case identifiers | Screen | Pass | Court, docket/case number, other party |
| Accessibility accommodations | Screen | Pass | Checkbox choices for interpreter, wheelchair, hearing, other |
| Supporting-document upload | Screen | Pass | `files` field and useful examples in explanatory text |
| Contact fields | Fields only | Pass | Email and international-phone datatypes |
| Birth information | Fields only | Pass | `BirthDate` and birth city |
| Household and income | Fields only | Pass | Integer household size and currency income |
| Contact preference | Fields only | Pass | Choice-backed contact method and time |
| Contact screen UI apply/save | Screen/UI | Pass | Applied through the visible button, enabled Save, persisted correctly |

All 13 calls returned HTTP 200. All generated candidate YAML passed the
server's DAYamlChecker validation. Before the final UI Save, the Playground
source was byte-for-byte unchanged. After Save, all fixture header, target,
unrelated-block, and Python-scalar comments remained present.

## Semantic bug found and fixed

Every initial full-screen response returned a generic
`continue_button_field: continue` alongside ordinary input fields. In
Docassemble, a question is completed either by its fields or by a continue
button field; combining them creates an unrelated, collision-prone completion
variable. Syntax validation did not catch this semantic problem.

`normalize_generated_screen()` now clears `continue_button_field` whenever the
screen has generated fields, and the model prompt explicitly requests an empty
value in that situation. A regression test covers the rule. The final live UI
query returned two correct contact fields, no continue-button field, no browser
error, and saved without adding `continue button field:` to YAML.

## Quality observations

The generated content was concise and generally strong. Datatype selection was
particularly consistent: date/time, currency/integer, `BirthDate`, email,
international phone, yes/no, choice, and multi-file prompts all matched the
requested tasks. Variable names were descriptive snake_case and no duplicate or
generic `field_1` names appeared.

The output remains a draft requiring developer review. For example, the
accessibility screen offered “Other” without automatically adding a follow-up
description field, and the income screen asked for a frequency even though the
amount labels specified monthly values. These are reasonable drafts rather
than blocking defects, but they illustrate why semantic review remains useful.
