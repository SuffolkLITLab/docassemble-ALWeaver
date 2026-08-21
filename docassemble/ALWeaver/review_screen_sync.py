"""Regenerate an interview's review screen from the YAML it has today.

A Weaver-drafted review screen is only correct on the day it is drafted. Authors
add screens, rename variables and split files, and the review screen quietly
falls behind, because nothing regenerates it
(SuffolkLITLab/docassemble-ALWeaver#865, and the same complaint in #400).

The generation itself is ALDashboard's ``review_screen_generator``, imported at
runtime: it already reads finished YAML rather than the Weaver's in-memory field
model, which is exactly what re-syncing needs, and keeping one implementation
means the Dashboard's "Generate a review screen draft" tool and this one cannot
drift. ALDashboard is an optional dependency here -- the Weaver's own linting
integration treats it the same way -- so callers get a clear message rather than
a traceback when it is not installed.

What this module adds on top of the Dashboard's generator:

* the whole interview, not one file: `include:` directives inside the project
  are followed so variables asked in an included file are reviewed too;
* the interview's own identity: the drafted block keeps the `id`, `event` and
  `question` the interview already uses, so the download screen's "Edit answers"
  button and the navigation still point at it;
* a real sync: the old review block, revisit screens and tables are replaced in
  place instead of a second review screen being appended.
"""

import re
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

__all__ = [
    "ALDashboardUnavailable",
    "collect_interview_yaml_texts",
    "generate_review_screen_yaml",
    "interview_scope",
    "project_include_chain",
    "review_screen_identity",
    "sync_review_screen",
]

# An interview that includes more than this many project files is either a
# mistake or a cycle we failed to spot; either way, stop walking.
MAX_INCLUDED_FILES = 40

_DOCUMENT_SEPARATOR_RE = re.compile(r"(?m)^---[ \t]*(?:#[^\r\n]*)?(?:\r\n|\n|\r|$)")


class ALDashboardUnavailable(RuntimeError):
    """Raised when the ALDashboard package needed for generation is missing."""


def _load_dashboard_generator():
    try:
        from docassemble.ALDashboard.review_screen_generator import (  # type: ignore
            generate_review_screen_yaml as dashboard_generate,
        )
    except Exception as err:  # pragma: no cover - depends on the server's packages
        raise ALDashboardUnavailable(
            "Drafting a review screen needs the ALDashboard package. Install "
            "docassemble.ALDashboard on this server and try again."
        ) from err
    return dashboard_generate


# ---------------------------------------------------------------------------
# Walking the interview's files
# ---------------------------------------------------------------------------


def _include_targets(yaml_text: str) -> List[str]:
    """Project-local files named by `include:` blocks, in the order listed.

    Only bare filenames count. `docassemble.AssemblyLine:assembly_line.yml`
    names another package, whose questions the author cannot edit here and whose
    review entries AssemblyLine supplies itself.
    """
    import yaml as pyyaml

    targets: List[str] = []
    try:
        documents = list(pyyaml.safe_load_all(yaml_text))
    except pyyaml.YAMLError:
        return targets
    for document in documents:
        if not isinstance(document, dict):
            continue
        included = document.get("include")
        if isinstance(included, str):
            included = [included]
        if not isinstance(included, list):
            continue
        for entry in included:
            name = str(entry or "").strip()
            if not name or ":" in name or "/" in name or "\\" in name:
                continue
            if not name.lower().endswith((".yml", ".yaml")):
                continue
            if name not in targets:
                targets.append(name)
    return targets


def project_include_chain(
    read_file, filename: str, *, max_files: int = MAX_INCLUDED_FILES
) -> List[str]:
    """Every project YAML file the interview pulls in, starting with itself.

    ``read_file`` takes a filename and returns its text. Files that cannot be
    read are skipped: an interview that includes a file from a package we cannot
    see should still get a review screen for the parts we can.
    """
    ordered: List[str] = []
    seen: Set[str] = set()
    queue: List[str] = [filename]
    while queue and len(ordered) < max_files:
        current = queue.pop(0)
        if current in seen:
            continue
        seen.add(current)
        try:
            text = read_file(current)
        except Exception:
            continue
        ordered.append(current)
        for target in _include_targets(text):
            if target not in seen:
                queue.append(target)
    return ordered


def interview_scope(
    read_file,
    filename: str,
    project_filenames: Optional[Sequence[str]] = None,
    *,
    max_files: int = MAX_INCLUDED_FILES,
) -> Tuple[List[str], List[str]]:
    """Work out which files make up the interview a review screen belongs to.

    Review screens are very often kept in a file of their own -- `review.yml`,
    `review_page.yml`, `review_screens.yml` -- that includes nothing and is
    included *by* the interviews that use it. Drafting from that file alone
    finds no questions at all, so the walk has to go up the include graph as
    well as down: the scope is every file reachable from the root interviews
    that pull this one in.

    A review screen shared by several interviews is scoped to all of them,
    which is what its author has to cover anyway.

    Returns ``(roots, filenames)``. ``roots`` is empty when the file is its own
    interview, in which case the scope is just its own include chain.
    """
    own_chain = project_include_chain(read_file, filename, max_files=max_files)
    candidates = [str(name) for name in (project_filenames or []) if name]
    if not candidates:
        return [], own_chain

    # Every candidate's chain is walked, so each file is read once and kept.
    texts: Dict[str, Any] = {}

    def cached_read(name: str) -> str:
        if name not in texts:
            try:
                texts[name] = read_file(name)
            except Exception as err:
                texts[name] = err
        value = texts[name]
        if isinstance(value, Exception):
            raise value
        return str(value)

    cache: Dict[str, List[str]] = {}
    for name in candidates:
        cache[name] = project_include_chain(cached_read, name, max_files=max_files)
    cache.setdefault(filename, own_chain)

    included_by_something: Set[str] = set()
    for name, chain in cache.items():
        included_by_something.update(chain[1:])

    roots = [
        name
        for name in candidates
        if name not in included_by_something and filename in cache.get(name, [])
    ]
    if not roots:
        return [], own_chain

    ordered: List[str] = []
    for root in roots:
        for name in cache[root]:
            if name not in ordered:
                ordered.append(name)
    return roots, ordered[:max_files]


def collect_interview_yaml_texts(
    read_file,
    filename: str,
    project_filenames: Optional[Sequence[str]] = None,
    *,
    max_files: int = MAX_INCLUDED_FILES,
) -> Tuple[List[str], List[str]]:
    """Return ``(filenames, yaml_texts)`` for the whole interview."""
    _roots, filenames = interview_scope(
        read_file, filename, project_filenames, max_files=max_files
    )
    texts: List[str] = []
    kept: List[str] = []
    for name in filenames:
        try:
            texts.append(read_file(name))
            kept.append(name)
        except Exception:
            continue
    return kept, texts


# ---------------------------------------------------------------------------
# Reading and splicing documents
# ---------------------------------------------------------------------------


def _documents(source: str) -> List[Dict[str, Any]]:
    """Character ranges for each YAML document, including its `---` separator.

    Concatenating ``source[doc["sep_start"]:doc["end"]]`` for every document
    reproduces the file exactly, so dropping a document is a pure deletion and
    everything else keeps its original formatting.
    """
    documents: List[Dict[str, Any]] = []
    separator_start = 0
    body_start = 0
    for match in _DOCUMENT_SEPARATOR_RE.finditer(source):
        documents.append(
            {"sep_start": separator_start, "start": body_start, "end": match.start()}
        )
        separator_start = match.start()
        body_start = match.end()
    documents.append(
        {"sep_start": separator_start, "start": body_start, "end": len(source)}
    )
    for document in documents:
        document["text"] = source[document["start"] : document["end"]]
    return documents


def _parsed(document_text: str) -> Optional[Dict[str, Any]]:
    import yaml as pyyaml

    if not document_text.strip():
        return None
    try:
        parsed = pyyaml.safe_load(document_text)
    except pyyaml.YAMLError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _list_name(value: Any, suffix: str) -> Optional[str]:
    text = str(value or "").strip()
    if text.endswith(suffix):
        name = text[: -len(suffix)]
        return name or None
    return None


def review_screen_identity(source_yaml: str) -> Dict[str, Any]:
    """The `id`, `event` and `question` of the review screen already in a file.

    Returned empty when the file has no review block yet, in which case the
    caller is drafting rather than syncing.
    """
    for document in _documents(source_yaml):
        parsed = _parsed(document["text"])
        if parsed is None or "review" not in parsed:
            continue
        return {
            "id": parsed.get("id"),
            "event": parsed.get("event"),
            "question": parsed.get("question"),
            "found": True,
        }
    return {"found": False}


def _generated_list_names(review_yaml: str) -> Set[str]:
    names: Set[str] = set()
    for document in _documents(review_yaml):
        parsed = _parsed(document["text"])
        if parsed is None:
            continue
        name = _list_name(parsed.get("table"), ".table")
        if name:
            names.add(name)
        name = _list_name(parsed.get("continue button field"), ".revisit")
        if name:
            names.add(name)
    return names


def sync_review_screen(source_yaml: str, review_yaml: str) -> Tuple[str, bool]:
    """Put ``review_yaml`` where the file's current review screen is.

    The review block is replaced in place, along with the revisit screens and
    tables for the lists the new draft also covers -- those are regenerated, so
    leaving the old copies behind would define the same table twice. A revisit
    screen for a list the new draft says nothing about is left alone: the author
    wrote it, not the Weaver.

    Returns the new source and whether an existing review screen was replaced;
    when there was none, the draft is appended.
    """
    regenerated = _generated_list_names(review_yaml)
    documents = _documents(source_yaml)

    review_index: Optional[int] = None
    drop: Set[int] = set()
    for index, document in enumerate(documents):
        parsed = _parsed(document["text"])
        if parsed is None:
            continue
        if "review" in parsed:
            if review_index is None:
                review_index = index
            drop.add(index)
            continue
        name = _list_name(parsed.get("table"), ".table")
        if name and name in regenerated:
            drop.add(index)
            continue
        name = _list_name(parsed.get("continue button field"), ".revisit")
        if name and name in regenerated and "review" not in parsed:
            drop.add(index)

    block = review_yaml.strip("\n")
    if review_index is None:
        joined = source_yaml.rstrip("\n")
        return f"{joined}\n---\n{block}\n", False

    parts: List[str] = []
    for index, document in enumerate(documents):
        if index in drop:
            if index == review_index:
                parts.append(f"\n---\n{block}\n")
            continue
        parts.append(source_yaml[document["sep_start"] : document["end"]])
    return "".join(parts).lstrip("\n"), True


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


def _apply_identity(
    review_yaml: str,
    *,
    screen_id: Optional[str],
    event_name: Optional[str],
    question_text: Optional[str],
) -> str:
    """Give the drafted review block the interview's own id, event and heading.

    ALDashboard's generator names its screen `review_form`, which is right for a
    standalone draft and wrong for an interview whose download screen already
    links to `review_<label>`. Newer Dashboard versions take these as arguments;
    this rewrite keeps the feature working against the released ones.
    """
    if not any([screen_id, event_name, question_text]):
        return review_yaml

    from ruamel.yaml import YAML
    from ruamel.yaml.compat import StringIO

    yaml = YAML()
    yaml.default_flow_style = False
    documents = list(yaml.load_all(review_yaml))
    for document in documents:
        if not isinstance(document, dict) or "review" not in document:
            continue
        if screen_id:
            document["id"] = screen_id
        if event_name:
            document["event"] = event_name
        if question_text:
            document["question"] = question_text
        break
    stream = StringIO()
    yaml.dump_all(documents, stream)
    return stream.getvalue()


def generate_review_screen_yaml(
    yaml_texts: Sequence[str],
    *,
    screen_id: Optional[str] = None,
    event_name: Optional[str] = None,
    question_text: Optional[str] = None,
) -> str:
    """Draft review-screen YAML for a whole interview.

    Raises ``ALDashboardUnavailable`` when the Dashboard package is not
    installed on this server.
    """
    dashboard_generate = _load_dashboard_generator()
    texts = [str(text or "") for text in yaml_texts if str(text or "").strip()]
    if not texts:
        raise ValueError("There is no YAML to draft a review screen from.")

    kwargs: Dict[str, Any] = {
        "build_revisit_blocks": True,
        # The Weaver's `sections:` are navigation headings, not events. Pointing
        # each one at the review screen would replace the interview's navigation
        # with a set of jumps to the recap.
        "point_sections_to_review": False,
    }
    supported = _supported_dashboard_kwargs(dashboard_generate)
    passthrough = {
        "review_id": screen_id,
        "review_event_name": event_name,
        "review_question": question_text,
    }
    handled_locally = False
    for name, value in passthrough.items():
        if value is None:
            continue
        if name in supported:
            kwargs[name] = value
        else:
            handled_locally = True

    review_yaml = dashboard_generate(texts, **kwargs)
    if handled_locally:
        review_yaml = _apply_identity(
            review_yaml,
            screen_id=screen_id if "review_id" not in supported else None,
            event_name=event_name if "review_event_name" not in supported else None,
            question_text=(
                question_text if "review_question" not in supported else None
            ),
        )
    return review_yaml


def _supported_dashboard_kwargs(dashboard_generate) -> Set[str]:
    import inspect

    try:
        return set(inspect.signature(dashboard_generate).parameters)
    except (TypeError, ValueError):  # pragma: no cover - builtins only
        return set()
