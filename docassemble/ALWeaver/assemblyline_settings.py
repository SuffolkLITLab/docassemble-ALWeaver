"""Round-trip helpers for graphical AssemblyLine interview settings.

AssemblyLine has two distinct setting families: publishing metadata stored in a
``metadata`` document, and exact-name Python variables normally defined in
``code`` blocks.  This module keeps that distinction explicit and writes the
latter to one Weaver-owned block so the graphical editor never has to guess
which arbitrary author code it is allowed to replace.
"""

from __future__ import annotations

import ast
import copy
import re
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple

import yaml

MANAGED_BLOCK_ID = "alweaver assemblyline settings"
DOCS_URL = (
    "https://assemblyline.suffolklitlab.org/docs/components/AssemblyLine/"
    "magic_variables/"
)


# Where each value shows up and what else it affects.  The question-driven Weaver
# explained this as you filled each screen in; the graphical panel shows every
# setting at once, so the explanation has to travel with the control.
FIELD_HELP: Dict[str, str] = {
    # Form identity and publishing
    "title": (
        "The form's name. Shown on the interview's first screen, in the browser "
        "tab, and in listings such as CourtFormsOnline."
    ),
    "short title": (
        "A shorter name, up to about 25 characters, used where the full title "
        "does not fit."
    ),
    "description": (
        "Helps people find your form. It is used for metadata and listings and is "
        "not displayed inside the interview."
    ),
    "can_I_use_this_form": (
        "Explain when someone can and cannot use this form -- conditions such as "
        "age, county, or the status of their case."
    ),
    "before_you_start": (
        "What the user needs to gather or know before they begin. Shown on the "
        "introduction screen. Markdown lists and bullets work here."
    ),
    "when_you_are_finished": (
        "What the user should do after they finish. Used for metadata and to "
        "guide the next-steps document."
    ),
    "landing_page_url": (
        "A public page about this form. Used by publishing and indexing tools; "
        "not shown to the user inside the interview."
    ),
    "authors": "Credited as the authors of the interview in published metadata.",
    "LIST_topics": (
        "LIST/NSMI taxonomy codes, such as HO-00-00-00-00. Referral sites use "
        "these to categorise the form."
    ),
    "original_form": "URLs for the official published version of the paper form.",
    "jurisdiction": (
        "A jurisdiction code such as NAM-US-US+MA. Used by publishing tools to "
        "place the form geographically."
    ),
    "allowed_courts": (
        "Restricts the courts this form can be filed in. Leave empty to allow "
        "every court the server knows about."
    ),
    "typical_role": (
        "Whether the person filling this out normally starts the case or responds "
        "to one. AssemblyLine uses it to word party questions."
    ),
    "efiling_enabled": "Optional publishing metadata. Leave off if unknown.",
    "integrated_efiling": "Optional publishing metadata. Leave off if unknown.",
    "integrated_email_filing": "Optional publishing metadata. Leave off if unknown.",
    "requires_notarization": (
        "Optional publishing metadata: the finished document has to be notarized."
    ),
    "unlisted": (
        "Keeps the interview out of public listings. It stays reachable by direct "
        "link."
    ),
    "estimated_completion_minutes": (
        "How long most people take, in minutes. Shown to the user before they start."
    ),
    "estimated_completion_delta": (
        "The plus-or-minus range on that estimate, in minutes."
    ),
    # Organization and locale
    "AL_ORGANIZATION_TITLE": (
        "The organization named in the terms of use, reminder messages, and the "
        "interview footer."
    ),
    "AL_ORGANIZATION_HOMEPAGE": (
        "Linked from the download screen and the terms of use as the "
        "organization's home page."
    ),
    "AL_DEFAULT_COUNTRY": (
        "Sets which country's address format and state list address questions use."
    ),
    "AL_DEFAULT_STATE": (
        "Preselects the state or province in address questions. Leave empty to "
        "make the user choose."
    ),
    "AL_DEFAULT_LANGUAGE": (
        "The language generated documents are written in. Separate from the "
        "interview's own language switching."
    ),
    "AL_DEFAULT_OVERFLOW_MESSAGE": (
        "Printed in a PDF field when the answer is too long for the space, "
        "pointing the reader at the addendum."
    ),
    # Interview behavior
    "al_form_type": (
        "Drives party wording, the next-steps document, and whether AssemblyLine "
        "asks court-related questions."
    ),
    "user_ask_role": (
        "Whether the user is treated as the party who started the case. Set it to "
        "unknown to have AssemblyLine ask."
    ),
    "al_person_answering": (
        "Whether the person at the keyboard is the litigant or someone helping "
        "them. Changes first- and third-person wording throughout."
    ),
    "al_form_requires_digital_signature": (
        "Adds the signature flow before the download screen. Turn it off for "
        "forms that are signed on paper."
    ),
    "al_typed_signature_prefix": (
        "Printed before a typed signature, for example /s/ Jane Doe."
    ),
    "al_typed_signature_font": (
        "The font a typed signature is rendered in. Leave empty for the "
        "AssemblyLine default."
    ),
    "speak_text": (
        "Shows the read-aloud control in the navigation bar. Needs a "
        "text-to-speech service configured on the server."
    ),
    # Languages
    "enable_al_language": (
        "Shows AssemblyLine's language switcher. Only useful once you have "
        "translations for the interview."
    ),
    "al_user_default_language": "The language the interview opens in.",
    "al_interview_languages": (
        "The languages offered in the switcher, as two-letter codes."
    ),
    # Repository and feedback
    "github_repo_name": (
        "The repository this package lives in. Used by the in-interview feedback "
        "form to file issues in the right place."
    ),
    "github_user": "The GitHub owner or organization for that repository.",
    # Next steps
    "al_next_steps_enabled": (
        "Includes the next-steps document in the download bundle. Turning it off "
        "keeps the file so you can turn it back on later."
    ),
    "al_next_steps_document_title": (
        "What the next-steps document calls the thing the user just made, for "
        'example "form" or "motion".'
    ),
    "al_next_steps_document_purpose": (
        "What the next-steps document calls what the user is asking for, for "
        'example "request" or "appeal".'
    ),
    "al_next_steps_help_organization": (
        "The organization the next-steps document tells the user to contact."
    ),
    "al_next_steps_help_url": "Where the next-steps document sends the user for help.",
    "al_next_steps_generate_qr_code": (
        "Prints a QR code in the next-steps document linking back to the interview."
    ),
    "al_next_steps_what_happens_next": (
        "The next-steps section describing what happens after the form is filed."
    ),
    "al_next_steps_what_can_decision_maker_do": (
        "The next-steps section describing the decisions a judge or clerk can make."
    ),
    "al_next_steps_what_happens_if_i_win": (
        "The next-steps section describing what follows if the request is granted."
    ),
}


# Settings AssemblyLine also resolves server-wide.  Writing one here overrides the
# server for this interview only, which the panel has to say out loud.
# The value is the Docassemble configuration key, or None when the fallback is an
# AssemblyLine literal rather than something in the server configuration.
SERVER_DEFAULTS: Dict[str, Optional[str]] = {
    "AL_ORGANIZATION_TITLE": "appname",
    "AL_ORGANIZATION_HOMEPAGE": "app homepage",
    "AL_DEFAULT_COUNTRY": None,
    "AL_DEFAULT_STATE": None,
    "AL_DEFAULT_LANGUAGE": None,
    "AL_DEFAULT_OVERFLOW_MESSAGE": None,
}

# What AssemblyLine falls back to when neither the interview nor the server sets
# the value (al_settings.yml).
ASSEMBLY_LINE_FALLBACKS: Dict[str, str] = {
    "AL_ORGANIZATION_TITLE": "docassemble",
    "AL_ORGANIZATION_HOMEPAGE": "https://courtformsonline.org",
    "AL_DEFAULT_COUNTRY": "US",
    "AL_DEFAULT_LANGUAGE": "en",
    "AL_DEFAULT_OVERFLOW_MESSAGE": "...",
}


def _field(
    key: str,
    label: str,
    kind: str = "text",
    default: Any = "",
    **kwargs: Any,
) -> Dict[str, Any]:
    result = {"key": key, "label": label, "kind": kind, "default": default}
    result.update(kwargs)
    result.setdefault("help", FIELD_HELP.get(key, ""))
    if key in SERVER_DEFAULTS:
        result.setdefault("server_default_key", SERVER_DEFAULTS[key])
        result.setdefault("has_server_default", True)
        if key in ASSEMBLY_LINE_FALLBACKS:
            result.setdefault("assembly_line_fallback", ASSEMBLY_LINE_FALLBACKS[key])
    return result


SETTINGS_SCHEMA: List[Dict[str, Any]] = [
    {
        "id": "identity",
        "label": "Form identity and publishing",
        "fields": [
            _field("title", "Title", scope="metadata", pair="title"),
            _field("short title", "Short title", scope="metadata", pair="title"),
            _field("description", "Description", "area", scope="metadata"),
            _field(
                "can_I_use_this_form",
                "Who can use this form?",
                "area",
                scope="metadata",
            ),
            _field("before_you_start", "Before you start", "area", scope="metadata"),
            _field(
                "when_you_are_finished",
                "When you are finished",
                "area",
                scope="metadata",
            ),
            _field(
                "landing_page_url", "Public landing page URL", "url", scope="metadata"
            ),
            _field("authors", "Authors", "list", [], scope="metadata"),
            _field("LIST_topics", "LIST topics", "list", [], scope="metadata"),
            _field("original_form", "Original form URLs", "list", [], scope="metadata"),
            _field("jurisdiction", "Jurisdiction code", scope="metadata"),
            _field("allowed_courts", "Allowed courts", "list", [], scope="both"),
            _field(
                "typical_role",
                "Typical user role",
                "choice",
                "unknown",
                scope="metadata",
                choices=["plaintiff", "defendant", "unknown", "na"],
            ),
            _field(
                "efiling_enabled",
                "E-filing enabled",
                "boolean",
                False,
                scope="metadata",
            ),
            _field(
                "integrated_efiling",
                "Integrated e-filing",
                "boolean",
                False,
                scope="metadata",
            ),
            _field(
                "integrated_email_filing",
                "Integrated email filing",
                "boolean",
                False,
                scope="metadata",
            ),
            _field(
                "requires_notarization",
                "Requires notarization",
                "boolean",
                False,
                scope="metadata",
            ),
            _field(
                "unlisted",
                "Keep interview unlisted",
                "boolean",
                False,
                scope="metadata",
            ),
            _field(
                "estimated_completion_minutes",
                "Estimated completion minutes",
                "integer",
                10,
                scope="metadata",
                pair="timing",
            ),
            _field(
                "estimated_completion_delta",
                "Estimate plus or minus",
                "integer",
                5,
                scope="metadata",
                pair="timing",
            ),
        ],
    },
    {
        "id": "organization",
        "label": "Organization and locale",
        "fields": [
            _field("AL_ORGANIZATION_TITLE", "Organization title"),
            _field("AL_ORGANIZATION_HOMEPAGE", "Organization homepage", "url"),
            _field(
                "AL_DEFAULT_COUNTRY", "Default country", default="US", pair="locale"
            ),
            _field("AL_DEFAULT_STATE", "Default state or province", pair="locale"),
            _field("AL_DEFAULT_LANGUAGE", "Default document language", default="en"),
            _field(
                "AL_DEFAULT_OVERFLOW_MESSAGE", "PDF overflow message", default="..."
            ),
        ],
    },
    {
        "id": "interview",
        "label": "Interview behavior",
        "fields": [
            _field(
                "al_form_type",
                "Form type",
                "choice",
                "other",
                choices=[
                    "starts_case",
                    "existing_case",
                    "appeal",
                    "other_form",
                    "letter",
                    "other",
                ],
            ),
            _field(
                "user_ask_role",
                "User role",
                "choice",
                "unknown",
                choices=["plaintiff", "defendant", "unknown"],
            ),
            _field(
                "al_person_answering",
                "Person answering",
                "choice",
                "user",
                choices=["user", "attorney", "advocate", "other"],
            ),
            _field(
                "al_form_requires_digital_signature",
                "Require a digital signature",
                "boolean",
                False,
            ),
            _field(
                "al_typed_signature_prefix", "Typed-signature prefix", default="/s/"
            ),
            _field("al_typed_signature_font", "Typed-signature font"),
            _field("speak_text", "Enable read-aloud control", "boolean", True),
        ],
    },
    {
        "id": "language",
        "label": "Languages",
        "fields": [
            _field(
                "enable_al_language",
                "Enable AssemblyLine language switching",
                "boolean",
                True,
            ),
            _field("al_user_default_language", "Default user language", default="en"),
            _field("al_interview_languages", "Supported languages", "list", ["en"]),
        ],
    },
    {
        "id": "repository",
        "label": "Repository and feedback",
        "fields": [
            _field("github_repo_name", "GitHub repository name", pair="github"),
            _field("github_user", "GitHub owner", pair="github"),
        ],
    },
    {
        "id": "next_steps",
        "label": "Next steps document",
        "fields": [
            _field("al_next_steps_enabled", "Include next steps", "boolean", True),
            _field(
                "al_next_steps_document_title",
                "Document name",
                default="form",
                pair="document_names",
            ),
            _field(
                "al_next_steps_document_purpose",
                "Request name",
                default="request",
                pair="document_names",
            ),
            _field("al_next_steps_help_organization", "Help organization", pair="help"),
            _field("al_next_steps_help_url", "Help URL", "url", pair="help"),
            _field("al_next_steps_generate_qr_code", "Add a QR code", "boolean", False),
            _field("al_next_steps_what_happens_next", "What happens next", "area"),
            _field(
                "al_next_steps_what_can_decision_maker_do",
                "What the decision maker can do",
                "area",
            ),
            _field(
                "al_next_steps_what_happens_if_i_win",
                "What happens if the request is granted",
                "area",
            ),
        ],
    },
    {
        "id": "advanced",
        "label": "Advanced and derived variables",
        "readonly": True,
        "notes": [
            "al_logo is an object backed by a file; edit it in Objects and Static files.",
            "addresses_to_search is executable court-routing logic; edit its code block directly.",
            "al_intro_screen is an interview-order event, not metadata.",
            "al_user_bundle, al_court_bundle, signature_fields, and trial_court are runtime structure.",
            "user_role and user_started_case are derived from al_form_type and user_ask_role.",
            "users and other_parties are AssemblyLine objects and should be edited in the object/screen tools.",
            "al_menu_items_custom_items may contain dynamic code; edit its data block directly.",
            "Server-wide AssemblyLine configuration is intentionally not editable here.",
        ],
        "fields": [],
    },
]


CODE_FIELDS = {
    field["key"]: field
    for section in SETTINGS_SCHEMA
    for field in section.get("fields", [])
    if field.get("scope") in {None, "both"}
}
METADATA_FIELDS = {
    field["key"]: field
    for section in SETTINGS_SCHEMA
    for field in section.get("fields", [])
    if field.get("scope") in {"metadata", "both"}
}


METADATA_DOCUMENT_ID = "metadata"

# What each kind of setting is, in one place, so the panel can explain itself
# rather than assuming the author already knows the difference.
PANEL_EXPLAINER = (
    "AssemblyLine reads two different kinds of setting, and both normally live "
    "in YAML you edit by hand. Publishing metadata -- title, description, "
    "jurisdiction, topics -- sits in the interview's metadata block and tells "
    "listing sites such as CourtFormsOnline what this form is. Predefined "
    "variables -- names like al_form_type or AL_DEFAULT_STATE -- have a special "
    "meaning to AssemblyLine and change how your interview looks and behaves. "
    "This page gathers both in one place, shows each one's exact name, and "
    "writes them back to the blocks named on each section."
)

_DOCUMENT_DESCRIPTIONS = {
    METADATA_DOCUMENT_ID: (
        "the interview's metadata block, read by AssemblyLine and by publishing "
        "sites"
    ),
    MANAGED_BLOCK_ID: (
        "a code block Weaver owns and rewrites in full; your own code blocks are "
        "never touched"
    ),
}


def _section_documents(section: Mapping[str, Any]) -> List[Dict[str, str]]:
    """Name the YAML documents a section's values are written to.

    Derived from the fields' own scopes rather than written out by hand, so it
    cannot drift when a field moves between metadata and code.
    """
    documents: List[Dict[str, str]] = []
    scopes = {field.get("scope") for field in section.get("fields", [])}
    if scopes & {"metadata", "both"}:
        documents.append(
            {
                "id": METADATA_DOCUMENT_ID,
                "kind": "metadata",
                "description": _DOCUMENT_DESCRIPTIONS[METADATA_DOCUMENT_ID],
            }
        )
    if scopes & {None, "both"}:
        documents.append(
            {
                "id": MANAGED_BLOCK_ID,
                "kind": "code",
                "description": _DOCUMENT_DESCRIPTIONS[MANAGED_BLOCK_ID],
            }
        )
    return documents


for _section in SETTINGS_SCHEMA:
    _section["documents"] = _section_documents(_section)
del _section


_SEPARATOR_RE = re.compile(r"(?m)^---[ \t]*(?:\r?\n|$)")


def _documents(source: str) -> List[Tuple[int, int, str]]:
    result: List[Tuple[int, int, str]] = []
    start = 0
    for match in _SEPARATOR_RE.finditer(source):
        result.append((start, match.start(), source[start : match.start()]))
        start = match.end()
    result.append((start, len(source), source[start:]))
    return result


def _code_assignments(code: str) -> Dict[str, Tuple[Any, bool]]:
    """Every supported setting this code assigns, and whether it is a literal.

    A setting the author computes -- ``al_form_type = form_type_for(case)`` --
    is reported as its source text with ``False``. The panel can display that,
    but it must never write it back: rendering it as a value would turn working
    code into a string.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return {}
    result: Dict[str, Tuple[Any, bool]] = {}
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        value_node = node.value
        if value_node is None:
            continue
        try:
            value = ast.literal_eval(value_node)
            is_literal = True
        except (ValueError, TypeError):
            value = ast.get_source_segment(code, value_node) or ""
            is_literal = False
        for target in targets:
            if isinstance(target, ast.Name) and target.id in CODE_FIELDS:
                result[target.id] = (value, is_literal)
    return result


def _literal_assignments(code: str) -> Dict[str, Any]:
    return {key: value for key, (value, _literal) in _code_assignments(code).items()}


def _rewrite_code_assignment(code: str, key: str, rendered: str) -> Optional[str]:
    """Replace the right-hand side of ``key = ...`` in a block of Python.

    Only the value expression is touched, so comments, ordering, and every other
    statement in the block survive. Returns None when the name is not assigned
    here, so the caller can fall back to Weaver's own block.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None

    # ast column offsets are UTF-8 byte offsets, so the edit is done on bytes.
    data = code.encode("utf-8")
    line_starts = [0]
    for line in code.splitlines(keepends=True):
        line_starts.append(line_starts[-1] + len(line.encode("utf-8")))

    for node in reversed(tree.body):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        value_node = node.value
        if value_node is None:
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == key for target in targets
        ):
            continue
        if value_node.end_lineno is None or value_node.end_col_offset is None:
            return None
        start = line_starts[value_node.lineno - 1] + value_node.col_offset
        end = line_starts[value_node.end_lineno - 1] + value_node.end_col_offset
        updated = data[:start] + rendered.encode("utf-8") + data[end:]
        return updated.decode("utf-8")
    return None


def _code_scalar_span(body: str) -> Optional[Tuple[int, int]]:
    """The exact source range of a block's ``code:`` scalar, header included."""
    try:
        root = yaml.compose(body)
    except yaml.YAMLError:
        return None
    if not isinstance(root, yaml.MappingNode):
        return None
    for key_node, value_node in root.value:
        if (
            isinstance(key_node, yaml.ScalarNode)
            and key_node.value == "code"
            and isinstance(value_node, yaml.ScalarNode)
        ):
            return value_node.start_mark.index, value_node.end_mark.index
    return None


def _render_code_scalar(original: str, code: str, newline: str) -> Optional[str]:
    """Re-render a ``code:`` block scalar around new code text.

    The header -- and any chomping indicator on it -- is copied from what was
    there, and every content line is re-indented to the depth the block already
    used, so the only thing that changes is the code itself.
    """
    header, separator, remainder = original.partition("\n")
    header = header.strip()
    if not separator or not header.startswith("|"):
        # Not a literal block scalar; rewriting it is not safe to guess at.
        return None
    indent = ""
    for line in remainder.splitlines():
        if line.strip():
            indent = line[: len(line) - len(line.lstrip())]
            break
    if not indent:
        return None
    rendered_lines = [
        indent + line if line.strip() else "" for line in code.split("\n")
    ]
    while rendered_lines and not rendered_lines[-1]:
        rendered_lines.pop()
    trailing = newline if original.endswith(("\n", "\r")) else ""
    return header + newline + newline.join(rendered_lines) + trailing


def rewrite_external_code_assignments(
    source: str, values: Mapping[str, Any], changed: Set[str]
) -> Tuple[str, Set[str]]:
    """Update changed settings in whichever author-owned block already assigns them.

    Two rules, and the second matters as much as the first:

    * A setting the author already assigns in their own block is updated
      *there*. Writing Weaver's copy as well would leave two blocks assigning
      one name and the winner decided by document order, so every key this
      finds is left out of the managed block whether or not it changed.
    * Only values the author actually changed on the panel are rewritten.
      Rewriting the rest would re-quote literals the author wrote by hand, and
      would flatten a computed value -- ``al_form_type = form_type_for(case)``
      reaches the panel as its source text, and writing that back through
      ``repr()`` would turn working code into a string.

    Returns the updated source and every key now owned by an author's block.
    """
    handled: Set[str] = set()
    updated_source = source
    # Later documents are rewritten first so earlier spans stay valid.
    for start, end, body in reversed(_documents(updated_source)):
        try:
            parsed = yaml.safe_load(body)
        except yaml.YAMLError:
            continue
        if not isinstance(parsed, dict) or parsed.get("id") == MANAGED_BLOCK_ID:
            continue
        code = parsed.get("code")
        if not isinstance(code, str):
            continue
        assigned = set(_literal_assignments(code)) & set(values)
        if not assigned:
            continue

        to_rewrite = assigned & changed
        if not to_rewrite:
            # Nothing to write, but the author still owns these names.
            handled |= assigned
            continue

        span = _code_scalar_span(body)
        if span is None:
            continue

        newline = "\r\n" if "\r\n" in body else "\n"
        rewritten = code
        rewritten_keys: Set[str] = set()
        for key in sorted(to_rewrite):
            replacement = _rewrite_code_assignment(
                rewritten, key, _render_code_value(key, values[key])
            )
            if replacement is not None:
                rewritten = replacement
                rewritten_keys.add(key)
        if not rewritten_keys:
            handled |= assigned
            continue

        scalar_start, scalar_end = span
        new_scalar = _render_code_scalar(
            body[scalar_start:scalar_end], rewritten, newline
        )
        if new_scalar is None:
            continue
        new_body = body[:scalar_start] + new_scalar + body[scalar_end:]

        # Refuse a patch that does not read back as the values just written.
        try:
            reparsed = yaml.safe_load(new_body)
        except yaml.YAMLError:
            continue
        if not isinstance(reparsed, dict) or not isinstance(reparsed.get("code"), str):
            continue
        read_back = _literal_assignments(reparsed["code"])
        if any(read_back.get(key) != values[key] for key in rewritten_keys):
            continue

        updated_source = updated_source[:start] + new_body + updated_source[end:]
        handled |= assigned
    return updated_source, handled


def _metadata(source: str) -> Tuple[Dict[str, Any], Optional[Tuple[int, int, str]]]:
    for start, end, body in _documents(source):
        try:
            parsed = yaml.safe_load(body)
        except yaml.YAMLError:
            continue
        if isinstance(parsed, dict) and isinstance(parsed.get("metadata"), dict):
            return dict(parsed["metadata"]), (start, end, body)
    return {}, None


def read_settings(source: str) -> Dict[str, Any]:
    """Read metadata and supported literal assignments from an interview."""
    values: Dict[str, Any] = {
        key: copy.deepcopy(field.get("default"))
        for key, field in {**METADATA_FIELDS, **CODE_FIELDS}.items()
    }
    metadata, _location = _metadata(source)
    for key in METADATA_FIELDS:
        if key in metadata:
            values[key] = metadata[key]

    sources: Dict[str, str] = {}
    # Settings the interview works out at runtime rather than storing a value
    # for. The panel shows these read-only: it has no value it could safely
    # write, and the author's expression is the real answer.
    computed: Dict[str, str] = {}
    for _start, _end, body in _documents(source):
        try:
            parsed = yaml.safe_load(body)
        except yaml.YAMLError:
            continue
        if not isinstance(parsed, dict) or not isinstance(parsed.get("code"), str):
            continue
        assignments = _code_assignments(parsed["code"])
        block_id = str(parsed.get("id") or "code block")
        for key, (value, is_literal) in assignments.items():
            values[key] = value
            sources[key] = block_id
            if is_literal:
                computed.pop(key, None)
            else:
                computed[key] = block_id

    return {
        "schema": copy.deepcopy(SETTINGS_SCHEMA),
        "values": values,
        "sources": sources,
        "computed": computed,
        "docs_url": DOCS_URL,
        "explainer": PANEL_EXPLAINER,
        "managed_block_id": MANAGED_BLOCK_ID,
        "metadata_document_id": METADATA_DOCUMENT_ID,
    }


def _coerce_value(field: Mapping[str, Any], value: Any) -> Any:
    kind = field.get("kind")
    if kind == "boolean":
        if not isinstance(value, bool):
            raise ValueError(f"{field['label']} must be true or false")
    elif kind == "integer":
        if value is None or (isinstance(value, str) and not value.strip()):
            return ""
        if isinstance(value, bool):
            raise ValueError(f"{field['label']} must be an integer")
        try:
            value = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field['label']} must be an integer") from exc
    elif kind == "list":
        if isinstance(value, str):
            value = [line.strip() for line in value.splitlines() if line.strip()]
        if not isinstance(value, list):
            raise ValueError(f"{field['label']} must be a list")
    elif kind == "choice":
        value = str(value or "")
        if value not in field.get("choices", []):
            raise ValueError(f"{field['label']} has an unsupported value")
    else:
        value = str(value or "")
    return value


def _render_code_value(key: str, value: Any) -> str:
    """One setting as the Python source that assigns it."""
    if CODE_FIELDS[key].get("kind") == "python":
        rendered = str(value or "None")
        try:
            ast.parse(rendered, mode="eval")
        except SyntaxError as exc:
            raise ValueError(
                f"{CODE_FIELDS[key]['label']} is not valid Python"
            ) from exc
        return rendered
    return repr(value)


def _managed_block(
    values: Mapping[str, Any],
    elsewhere: Optional[Set[str]] = None,
    computed: Optional[Mapping[str, str]] = None,
) -> str:
    lines = [
        f"id: {MANAGED_BLOCK_ID}",
        "initial: True",
        "code: |",
        "  # Managed by the graphical AssemblyLine settings editor.",
    ]
    for key in CODE_FIELDS:
        if key not in values:
            continue
        lines.append(f"  {key} = {_render_code_value(key, values[key])}")
    for key in sorted(elsewhere or ()):
        # Say where a setting went instead of leaving a silent gap here.
        lines.append(f"  # {key} is set in one of your own code blocks, not here.")
    for key in sorted(computed or ()):
        lines.append(f"  # {key} is computed by your own code, and is left alone.")
    return "\n".join(lines) + "\n"


def _replace_or_insert_managed(source: str, block: str) -> str:
    newline = "\r\n" if "\r\n" in source else "\n"
    block = block.replace("\n", newline)
    for start, end, body in _documents(source):
        try:
            parsed = yaml.safe_load(body)
        except yaml.YAMLError:
            continue
        if isinstance(parsed, dict) and parsed.get("id") == MANAGED_BLOCK_ID:
            leading = body[: len(body) - len(body.lstrip("\r\n"))]
            trailing = body[len(body.rstrip("\r\n")) :]
            return (
                source[:start]
                + leading
                + block.rstrip("\r\n")
                + trailing
                + source[end:]
            )

    # Put initial settings before the first mandatory block. Existing document
    # bytes are otherwise untouched.
    insertion = None
    for start, _end, body in _documents(source):
        try:
            parsed = yaml.safe_load(body)
        except yaml.YAMLError:
            continue
        if isinstance(parsed, dict) and parsed.get("mandatory") is True:
            insertion = start
            break
    document = block.rstrip("\r\n") + newline + "---" + newline
    if insertion is None:
        prefix = source
        if prefix and not prefix.endswith(("\n", "\r")):
            prefix += newline
        if prefix:
            prefix += "---" + newline
        return prefix + block
    return source[:insertion] + document + source[insertion:]


def _yaml_scalar(value: Any) -> str:
    """Serialize one scalar without PyYAML's document-end marker."""
    rendered = yaml.safe_dump(
        value,
        allow_unicode=True,
        default_flow_style=True,
        width=10_000,
    ).strip()
    if rendered.endswith("\n..."):
        rendered = rendered[:-4]
    elif rendered == "...":
        rendered = "''"
    return rendered


def _literal_block_value(
    value: str,
    *,
    content_indent: int,
    newline: str,
    original_fragment: str = "",
) -> str:
    """Render text as a literal block, retaining an existing chomping marker."""
    header_match = re.match(r"^([|>][1-9]?[+-]?)", original_fragment)
    if header_match:
        header = header_match.group(1).replace(">", "|", 1)
    else:
        header = "|" if value.endswith(("\n", "\r")) else "|-"
    normalized = value.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
    if not normalized:
        return header
    indentation = " " * content_indent
    return (
        header
        + newline
        + newline.join(
            indentation + line if line else "" for line in normalized.split("\n")
        )
    )


def _metadata_value_fragment(
    value: Any,
    *,
    value_node: Optional[yaml.Node],
    original_fragment: str,
    key_indent: int,
    newline: str,
) -> str:
    """Serialize one changed value while favoring readable literal text."""
    existing_block = isinstance(value_node, yaml.ScalarNode) and value_node.style in {
        "|",
        ">",
    }
    if isinstance(value, str) and (existing_block or "\n" in value or "\r" in value):
        return _literal_block_value(
            value,
            content_indent=key_indent + 2,
            newline=newline,
            original_fragment=original_fragment,
        )
    if isinstance(value, list):
        if not value:
            return "[]"
        indentation = " " * (key_indent + 2)
        items: List[str] = []
        for item in value:
            if isinstance(item, str) and ("\n" in item or "\r" in item):
                literal = _literal_block_value(
                    item,
                    content_indent=key_indent + 4,
                    newline=newline,
                )
                items.append("- " + literal)
            else:
                items.append("- " + _yaml_scalar(item))
        if isinstance(value_node, yaml.SequenceNode) and not value_node.flow_style:
            return items[0] + "".join(
                newline + indentation + item for item in items[1:]
            )
        return newline + newline.join(indentation + item for item in items)
    return _yaml_scalar(value)


def _metadata_mapping_node(body: str) -> Optional[yaml.MappingNode]:
    try:
        root = yaml.compose(body)
    except yaml.YAMLError:
        return None
    if not isinstance(root, yaml.MappingNode):
        return None
    for key_node, value_node in root.value:
        if (
            isinstance(key_node, yaml.ScalarNode)
            and key_node.value == "metadata"
            and isinstance(value_node, yaml.MappingNode)
        ):
            return value_node
    return None


def _update_metadata(source: str, updates: Mapping[str, Any]) -> str:
    """Patch changed metadata values without re-serializing the document."""
    _metadata_values, location = _metadata(source)
    if location is None:
        raise ValueError("No metadata document was found")
    start, end, body = location
    metadata_node = _metadata_mapping_node(body)
    if metadata_node is None:
        raise ValueError("The metadata mapping could not be edited safely")
    newline = "\r\n" if "\r\n" in body else "\n"
    existing: Dict[str, Tuple[yaml.Node, yaml.Node]] = {}
    for key_node, value_node in metadata_node.value:
        if not isinstance(key_node, yaml.ScalarNode) or key_node.value in existing:
            raise ValueError("The metadata mapping contains unsupported duplicate keys")
        existing[str(key_node.value)] = (key_node, value_node)

    operations: List[Tuple[int, int, str]] = []
    missing: List[Tuple[str, Any]] = []
    for key, value in updates.items():
        if key not in existing:
            missing.append((key, value))
            continue
        key_node, value_node = existing[key]
        value_start = value_node.start_mark.index
        value_end = value_node.end_mark.index
        if (
            isinstance(value_node, yaml.SequenceNode)
            and not value_node.flow_style
            and value_node.value
        ):
            # A block sequence's node ends where the *next* token begins, so it
            # swallows any comment or blank line sitting between this value and
            # the key below it. The last item's own end is where the value
            # really stops. Scalars and block scalars already end accurately.
            value_end = value_node.value[-1].end_mark.index
        fragment = body[value_start:value_end]
        replacement = _metadata_value_fragment(
            value,
            value_node=value_node,
            original_fragment=fragment,
            key_indent=key_node.start_mark.column,
            newline=newline,
        )
        # PyYAML ends a block value's node after the newline *and* the
        # indentation of whatever comes next, so that run is layout rather than
        # value. `_metadata_value_fragment` only ever returns content, so the
        # run has to be carried over: without it a multi-line value -- a list
        # with more than one item, or a literal block -- swallows the key that
        # follows it onto its own last line.
        trailing_layout = fragment[len(fragment.rstrip(" \t\r\n")) :]
        if trailing_layout and not replacement.endswith(trailing_layout):
            replacement += trailing_layout
        operations.append((value_start, value_end, replacement))

    if missing:
        key_indent = (
            metadata_node.value[0][0].start_mark.column
            if metadata_node.value
            else metadata_node.start_mark.column
        )
        insertion_at = len(body.rstrip("\r\n"))
        addition_lines: List[str] = []
        for key, value in missing:
            fragment = _metadata_value_fragment(
                value,
                value_node=None,
                original_fragment="",
                key_indent=key_indent,
                newline=newline,
            )
            separator = "" if fragment.startswith(newline) else " "
            addition_lines.append(" " * key_indent + key + ":" + separator + fragment)
        prefix = (
            ""
            if insertion_at == 0 or body[:insertion_at].endswith(("\n", "\r"))
            else newline
        )
        operations.append(
            (insertion_at, insertion_at, prefix + newline.join(addition_lines))
        )

    updated_body = body
    for operation_start, operation_end, replacement in sorted(
        operations, key=lambda item: item[0], reverse=True
    ):
        updated_body = (
            updated_body[:operation_start] + replacement + updated_body[operation_end:]
        )

    # Refuse a patch that does not round-trip to the submitted values.
    parsed = yaml.safe_load(updated_body)
    parsed_metadata = parsed.get("metadata") if isinstance(parsed, dict) else None
    if not isinstance(parsed_metadata, dict):
        raise ValueError("The metadata mapping could not be edited safely")
    for key, value in updates.items():
        parsed_value = parsed_metadata.get(key)
        if isinstance(value, str) and isinstance(parsed_value, str):
            if parsed_value.rstrip("\r\n") != value.rstrip("\r\n"):
                raise ValueError(f"Metadata value {key!r} did not round-trip safely")
        elif parsed_value != value:
            raise ValueError(f"Metadata value {key!r} did not round-trip safely")
    return source[:start] + updated_body + source[end:]


def update_settings(source: str, submitted: Mapping[str, Any]) -> str:
    """Update supported settings, preserving every unrelated YAML document."""
    if not isinstance(submitted, Mapping):
        raise ValueError("settings must be an object")
    unknown = set(submitted) - set(METADATA_FIELDS) - set(CODE_FIELDS)
    if unknown:
        raise ValueError("Unsupported settings: " + ", ".join(sorted(unknown)))

    settings = read_settings(source)
    current = settings["values"]
    computed: Dict[str, str] = settings["computed"]
    metadata_updates: Dict[str, Any] = {}
    code_values = {key: current[key] for key in CODE_FIELDS if key not in computed}
    changed_code: Set[str] = set()
    for key, raw_value in submitted.items():
        if key in computed:
            # The interview computes this one. There is no value the panel could
            # write that would not replace the author's expression, and the
            # control is read-only for exactly that reason, so anything that
            # arrives for it is ignored rather than validated.
            continue
        field = METADATA_FIELDS.get(key) or CODE_FIELDS[key]
        value = _coerce_value(field, raw_value)
        if key in METADATA_FIELDS and value != current.get(key):
            metadata_updates[key] = value
        if key in CODE_FIELDS:
            code_values[key] = value
            if value != current.get(key):
                changed_code.add(key)

    updated = _update_metadata(source, metadata_updates) if metadata_updates else source
    # A setting the author already assigns in their own block is updated there.
    # Adding Weaver's copy on top would leave two blocks assigning one name.
    updated, elsewhere = rewrite_external_code_assignments(
        updated, code_values, changed_code
    )
    managed_values = {
        key: value for key, value in code_values.items() if key not in elsewhere
    }
    return _replace_or_insert_managed(
        updated, _managed_block(managed_values, elsewhere, computed)
    )
