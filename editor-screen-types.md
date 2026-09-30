# Standalone question screens in `/al/editor`

The Screen tab recognizes `signature`, `yesno`, `noyes`, `yesnomaybe`,
`noyesmaybe`, `buttons`, `choices`, `dropdown`, `combobox`, and standalone
`field`. These screens are available in the Add block menu under **Other**.
Regular `fields` questions remain the recommended layout for new questions.

Signature screens have controls for the signature variable, the Markdown/Mako
caption (`under`), pen color, and required/optional status. The usual question
text and options, including `generic object` and `validation code`, still apply.
An existing computed `required` value stays read-only in the graphical controls
and can be changed in YAML. The preview shows desktop/mobile layouts and a sample
stroke in the chosen color; it does not collect a signature or execute Mako.
AssemblyLine's generic `ALIndividual` signature screen usually needs no override.

Other standalone screens expose their answer variable and, for static choices,
editable labels and typed values. Button metadata (URLs, colors, conditions) and
nested actions survive edits. Nested actions, computed choice lists, and other
advanced settings are edited in YAML. The preview does not execute actions or
Python-generated choices. `buttons` without `field` remains an action screen.

On graphical save, the deprecated combination of `field` and `fields` becomes
`continue button field` and `fields`. An explicit `continue button field` takes
precedence. Standalone `field` and `field` with choices/buttons keep their meaning.

## Interview audit

On September 26, 2026, the local `~/all_interviews/repos` corpus contained 338
YAML files. Of those, 335 parsed successfully, containing 2,276 question blocks.
The standalone screen patterns were:

| Pattern | Screens |
| --- | ---: |
| Signature | 23 |
| Buttons | 96 |
| Yes/no | 37 |
| No/yes | 1 |
| Yes/no/maybe | 10 |
| Choices | 8 |
| Dropdown | 9 |
| `field` without one of the above or `review` | 62 |

All 246 matching blocks passed a serializer-to-source-patcher data round trip,
allowing the three legacy `field` + `fields` conversions. Examples include
CLAGuardianship's conditional signer captions, MAInformalAppelleeBrief's standalone
signature variable, ALAffidavitOfIndigency's exit URL, and AppealsMotionToReconsider's
nested code action. Regression tests also cover AssemblyLine's generic signature
with accessible alt text, typed button values, computed choices, and source
comments. No corpus examples used standalone `noyesmaybe` or `combobox`; these
have synthetic coverage.

The audit also found existing `review` screens and `fields` with `list collect`.
`list collect`, `action buttons`, and layout modifiers such as `pre`, `post`, and
`right` are preserved but do not have dedicated graphical controls in this change.
Three files with existing YAML parse errors were excluded: StudentEvaluations's
`massachusetts_educational_evaluations_basic_information.yml`, SNAP's
`SnapCalculator-calculation.yml`, and MTVHousing's `Motion_to_Vacate.yml`.

The relevant Docassemble reference is
[Setting variables with questions](https://docassemble.org/docs/fields.html),
especially its [signature section](https://docassemble.org/docs/fields.html#signature).
