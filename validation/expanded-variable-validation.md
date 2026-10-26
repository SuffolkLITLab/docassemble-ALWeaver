# Expanded variable validation

Branch: `feature/expanded-variable-support`. Base: `cbc16e38489dc67d45bb748a25f3a32fbe077a87`.

Exact fixtures, downloaded outputs, checksums and a runnable verifier are published in the [unlisted evidence gist](https://gist.github.com/nonprofittechy/720601c37819d9801958c5b67b1c6d5a). The gist also explains the false-positive controls and corpus changes.

## Automated checks

- Final full Weaver suite at commit preparation: **1,564 passed, 1 skipped** (298.67 seconds).
- Final focused generation, question-library, review and editor suite: 282 passed, 207 subtests passed.
- Mypy: 145 source files, no issues. JavaScript `npm run check` passed.
- Companion AssemblyLine address-block tests: 2 passed, 2 subtests passed. The full upstream file has an existing `test_address_required` failure reproduced against the unchanged sibling checkout.
- Example interviews passed DAYamlChecker. Python formatting and `git diff --check` passed.

## Existing documents

The requested `~/all_repos` directory was absent. The available corpus at `~/all_interviews/repos` contains 195 PDF/DOCX templates. Both baseline and changed importers processed all 195 without errors. 187 were unchanged; the eight changes add name dependencies for existing `address_block()` calls and correct five singleton/list inferences confirmed against authored object declarations. No new unrelated objects were inferred. See `variable-recognition-corpus.json` for individual changes. This is a recognition regression audit, not a controlled throughput benchmark or execution of every existing interview.

## Independent reviews

Claude and `agy --model gemini-4-argon-high` reviewed the uncommitted implementation. Raw initial responses are retained beside this report. Claude also reviewed the fixes. Reproduced findings fixed in this branch:

- Clear generated questions before regrouping explicit address declarations.
- Honor explicit address types over person guesses; preserve raw dotted PDF labels and the DOCX street string.
- Gather/edit bare singleton people through their names; collect names before combined address rendering, including after address-trigger deduplication.
- Match service-address segments at boundaries; service-only labels do not invent people.
- Group address review entries; synchronize separately allocated authored screen fields with the declared address mapping.
- Preserve authored circuit screens and field definitions rather than adding a conflicting fallback.
- Recognize existing authored address questions in the library, including `address_fields()` code; county-only questions do not hide the street-address question.
- Match the service recipe's configurable choices to AssemblyLine's question/document value structure.

Not all reviewer assertions were correct. In particular, generic service questions exist in AssemblyLine, and Argon's claims about 66 corpus files, three PDF changes and signature-date changes do not match the saved 195-document comparison. Those claims were rejected after checking source and data. A county attribute remains a custom question because the generic address question does not collect county. Nested people and legacy-wizard row parity remain explicit follow-ups.

## Localhost

Installed the companion AssemblyLine runtime fix and this Weaver branch using `dainstall --server localhost`, with a final Weaver restart after review fixes. Tests used a disposable developer Playground project and synthetic data, without contacting users or sending email.

- Generated real PDF and DOCX interviews through `/al/api/v1/weaver`, uploaded templates and YAML to Playground, and completed both in Chromium.
- Reached download after name, home address, standalone property address, grandchild, service method/address/date, and circuit questions.
- Downloaded and inspected completed PDF output and actual DOCX output. Both contain the name plus address; the address-only expression omits the name.
- Used the review screen to edit the property street from `456 Oak Street` to `999 Review Lane`; regenerated PDF and DOCX both contain the new value.
- Ran `standalone-address.yml` to its summary without a person-name question.
- Ran `service-recipients.yml`, selected two already-collected parties, and reached per-recipient service questions and the summary. Changed Jordan to `in_person` at a different address while Alex retained `mail`.
- Verified the live editor offers Address, successfully declares `property_address: ALAddress`, and preserves surrounding comments, quotes and existing object declarations.

The corpus interviews were not all run on localhost. Confidential-address behavior is covered by the focused runtime probe, not by a full browser matrix. Zero-person lists, row overflow, provider-specific circuit derivations, and nested representation still need release acceptance. No release versions or issue closures are claimed.
