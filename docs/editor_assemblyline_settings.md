# AssemblyLine settings in the graphical Weaver

The question-driven Weaver collected both descriptive metadata and values that
AssemblyLine resolves by exact Python variable name. The graphical editor keeps
those concepts separate:

- publishing/discovery values remain in the interview's `metadata` document;
- supported predefined variables are written to the Weaver-owned
  `alweaver assemblyline settings` code block;
- executable logic, objects, events, and derived runtime values remain in their
  native graphical or YAML/code editors.

The settings endpoint uses an expected source revision and validates the whole
candidate interview before writing. It replaces only the metadata document and
the Weaver-owned block; author-owned code blocks are not rewritten.

The settings panel is searchable by section, friendly label, or exact metadata
key/magic-variable name. Each control displays that exact name. Controls use a
single-column layout by default; only related pairs, such as title/short title,
country/state, repository owner/name, and the two timing values, share a row.

## Question-driven workflow comparison

| Original Weaver screen or decision | Graphical auto-draft coverage | Graphical access pattern |
| --- | --- | --- |
| Form identity, description, eligibility, preparation, and completion prose | AI proposes the descriptive draft; exact publishing fields remain reviewable | **AssemblyLine settings** at any time |
| Output form versus data-only survey | Changes the generated interview structure and cannot be inferred safely | Deterministic project-creation choice |
| Form type, typical role, and default state | Auto-draft may infer them, but a wrong value changes downstream AssemblyLine behavior | Deterministic project-creation choices, then **AssemblyLine settings** |
| Template inspection, field typing, labels, and screen grouping | Core strength of auto-drafting; the graphical field and screen editors expose the result | Auto-draft followed by normal graphical editing |
| Organization, locale, language, signatures, repository, and accessibility variables | Not all warrant interrupting project creation, but they should not require locating exact-name code assignments | Searchable **AssemblyLine settings** |
| Next-steps inclusion and prose | Inclusion changes package structure; prose can be edited later | Creation-time include choice plus anytime `al_next_steps_*` settings |
| Next-steps DOCX selection/customization | A normal settings save must not destroy Word edits | Explicit, confirmed **Back up and replace with standard shell** action only |
| Bundles, signature fields, court routing, parties, menus, and order events | These are dynamic objects, executable logic, or interview structure—not scalar metadata | Their native object, field, order, data, or code editors |
| Review and package download | Replaced by continuous graphical review, validation, and project files | Normal editor/project workflow |

The creation dialog is therefore reserved for deterministic choices that alter
the generated structure. The anytime panel handles scalar publishing metadata
and literal predefined variables. Dynamic code and objects remain visible as
advanced coverage boundaries instead of being deceptively flattened into text
fields.

## Coverage of AssemblyLine special variables

The settings panel directly supports:

- organization/locale: `AL_ORGANIZATION_TITLE`,
  `AL_ORGANIZATION_HOMEPAGE`, `AL_DEFAULT_COUNTRY`, `AL_DEFAULT_STATE`,
  `AL_DEFAULT_LANGUAGE`, and `AL_DEFAULT_OVERFLOW_MESSAGE`;
- interview behavior: `al_form_type`, `user_ask_role`,
  `al_person_answering`, `allowed_courts`,
  `al_form_requires_digital_signature`, `al_typed_signature_prefix`,
  `al_typed_signature_font`, and `speak_text`;
- languages: `enable_al_language`, `al_user_default_language`, and
  `al_interview_languages`;
- repository information: `github_repo_name` and `github_user`;
- the stable `al_next_steps_*` values used by generated next-steps shells.

The panel explains but does not flatten these into metadata:

- `al_logo` is an object backed by a static file;
- `addresses_to_search` and dynamic menu items are executable logic;
- `al_intro_screen` is an interview-order event;
- `al_user_bundle`, `al_court_bundle`, `signature_fields`, and `trial_court`
  are runtime structure;
- `user_role` and `user_started_case` are derived;
- `users` and `other_parties` are AssemblyLine objects;
- server-wide settings belong in the Docassemble configuration.

This classification follows the official [AssemblyLine special-variable
documentation](https://assemblyline.suffolklitlab.org/docs/components/AssemblyLine/magic_variables/).

## Auto-drafting choices

Project creation asks for the choices that materially change generated output:

- downloadable forms or a data-only survey;
- form type and typical user role, with an automatic option;
- default state/province;
- next-steps inclusion; and
- left navigation.

AI remains responsible for proposed prose, labels, types, and screen grouping.
All deterministic choices can be reviewed later in AssemblyLine settings.

## Next-steps lifecycle

Form projects always receive the YAML wiring and a reusable form-type-specific
DOCX shell. Turning next steps off disables its `ALDocument`; it does not delete
the file, so the author can turn it on later without regeneration.

Ordinary next-steps edits update only `al_next_steps_*` values in YAML and never
overwrite the DOCX. Changing `al_form_type` also preserves the current DOCX.
The explicit **Back up and replace with standard shell** action is the only
graphical operation that replaces it. That action:

1. requires a confirmation flag;
2. copies the current DOCX to a unique `.pre-weaver-reset` backup; and
3. installs the standard runtime shell for the selected form type.

Generated shells refer to runtime `al_next_steps_*` values rather than the
temporary `interview` object used while the original Weaver runs. Generation
also normalizes the historical `document_concept`/`document_purpose` mismatch
and corrects the condition guarding the “request granted” instructions.

## Remaining template-ingestion boundary

The editor accepts multiple uploaded files so they can be retained in the
project, but the generator currently builds attachment and question YAML from
the first document. Until multi-document generation is implemented in
`generate_interview_from_path`, the creation screen must describe this boundary
plainly and must not imply that every uploaded file was automated.
