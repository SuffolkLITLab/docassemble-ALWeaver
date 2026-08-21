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
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

__all__ = [
    "ALDashboardUnavailable",
    "carry_over_unmatched_entries",
    "collect_interview_yaml_texts",
    "ensure_revisit_tables",
    "inferred_objects_document",
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


def _generated_tables(yaml_text: str) -> Set[str]:
    """Lists that ``yaml_text`` defines a `<name>.table` block for."""
    names: Set[str] = set()
    for document in _documents(yaml_text):
        parsed = _parsed(document["text"])
        if parsed is None:
            continue
        name = _list_name(parsed.get("table"), ".table")
        if name:
            names.add(name)
    return names


def _generated_revisits(yaml_text: str) -> Set[str]:
    """Lists that ``yaml_text`` defines a `<name>.revisit` screen for."""
    names: Set[str] = set()
    for document in _documents(yaml_text):
        parsed = _parsed(document["text"])
        if parsed is None or "review" in parsed:
            continue
        name = _list_name(parsed.get("continue button field"), ".revisit")
        if name:
            names.add(name)
    return names


def _declared_object_names(yaml_texts: Sequence[str]) -> Set[str]:
    """Every object named in an `objects:` block anywhere in scope."""
    names: Set[str] = set()
    for text in yaml_texts:
        for document in _documents(str(text or "")):
            parsed = _parsed(document["text"])
            if parsed is None:
                continue
            objects = parsed.get("objects")
            if isinstance(objects, dict):
                names.update(str(key) for key in objects)
            elif isinstance(objects, list):
                for entry in objects:
                    if isinstance(entry, dict):
                        names.update(str(key) for key in entry)
    return names


def _reviewed_list_names(source_yaml: str) -> List[str]:
    """Lists the file already treats as reviewable, in the order they appear.

    A `table: plaintiffs.table` block, or a review entry pointing at
    `plaintiffs.revisit`, is the interview saying "this is a list people edit
    from the review screen" just as clearly as an `objects:` block does.
    """
    names: List[str] = []

    def remember(name: Optional[str]) -> None:
        if name and name not in names and not any(c in name for c in ".[]"):
            names.append(name)

    for document in _documents(source_yaml):
        parsed = _parsed(document["text"])
        if parsed is None:
            continue
        remember(_list_name(parsed.get("table"), ".table"))
        remember(_list_name(parsed.get("continue button field"), ".revisit"))
        review = parsed.get("review")
        if isinstance(review, list):
            for entry in review:
                if isinstance(entry, dict):
                    remember(_list_name(entry.get("Edit"), ".revisit"))
    return names


def inferred_objects_document(yaml_texts: Sequence[str]) -> Optional[str]:
    """An `objects:` document for reviewable lists nothing in scope declares.

    AssemblyLine declares `plaintiffs`, `defendants` and `courts` in its own
    package, which the include walk deliberately does not follow -- an author
    cannot edit those files from here. Without this, drafting over a
    Weaver-generated interview silently drops the review entries for exactly
    those lists, because the generator only knows about a list it has seen an
    `objects:` block for.

    The class name is a stand-in: it never reaches the file, and the generator
    only asks whether the type looks like a list.
    """
    declared = _declared_object_names(yaml_texts)
    reviewed: List[str] = []
    for text in yaml_texts:
        for name in _reviewed_list_names(str(text or "")):
            if name not in reviewed:
                reviewed.append(name)
    missing = [name for name in reviewed if name not in declared]
    if not missing:
        return None
    lines = ["objects:"]
    lines.extend(f"  - {name}: DAList" for name in missing)
    return "\n".join(lines) + "\n"


def _round_trip_yaml():
    from ruamel.yaml import YAML

    yaml = YAML()
    yaml.default_flow_style = False
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.width = 4096
    yaml.preserve_quotes = True
    return yaml


def carry_over_unmatched_entries(review_yaml: str, source_yaml: str) -> Tuple[str, int]:
    """Keep review entries the draft has no opinion about.

    Drafting reads the interview's YAML, so it only knows about variables this
    project asks for. `docket_number` and the rest of AssemblyLine's built-in
    questions live in a package the walk does not follow, and dropping their
    entries would quietly shrink the review screen every time it is synced --
    which is worse than carrying a stale entry the author can see in the diff
    and delete.

    Entries are matched by their "Edit" target. A `note:` separator is not
    carried over: the draft regenerates the entries it labelled, so it would
    arrive as a heading with nothing under it.

    Returns the new draft and how many entries were kept.
    """
    from ruamel.yaml.compat import StringIO

    yaml = _round_trip_yaml()
    try:
        draft_documents = list(yaml.load_all(review_yaml))
        source_documents = list(yaml.load_all(source_yaml))
    except Exception:
        return review_yaml, 0

    draft_review = None
    for document in draft_documents:
        if isinstance(document, dict) and isinstance(document.get("review"), list):
            draft_review = document["review"]
            break
    if draft_review is None:
        return review_yaml, 0

    drafted_targets = {
        str(entry.get("Edit"))
        for entry in draft_review
        if isinstance(entry, dict) and entry.get("Edit") is not None
    }

    kept = 0
    for document in source_documents:
        if not isinstance(document, dict) or not isinstance(
            document.get("review"), list
        ):
            continue
        for entry in document["review"]:
            if not isinstance(entry, dict):
                continue
            target = entry.get("Edit")
            if target is None or str(target) in drafted_targets:
                continue
            draft_review.append(entry)
            drafted_targets.add(str(target))
            kept += 1
        break

    if not kept:
        return review_yaml, 0

    stream = StringIO()
    yaml.dump_all(draft_documents, stream)
    return stream.getvalue(), kept


_FALLBACK_TABLE = """table: {name}.table
rows: {name}
columns:
  - Name: |
      row_item
edit: True
confirm: True
"""


def ensure_revisit_tables(
    review_yaml: str, existing_yaml: Union[str, Sequence[str]] = ""
) -> str:
    """Give every drafted revisit screen a table to show.

    A revisit screen's whole body is `${{ <list>.table }}`, so one without a
    matching `table:` block is a screen that errors the moment somebody opens
    it. The generator omits the table when it never saw an indexed field for
    that list, and the file being synced may not have one either.
    """
    if isinstance(existing_yaml, str):
        existing_texts: Sequence[str] = [existing_yaml]
    else:
        existing_texts = list(existing_yaml)
    revisits = _generated_revisits(review_yaml)
    have = _generated_tables(review_yaml)
    # Every file in scope counts: in a project that keeps its review screen in
    # its own file, the table it displays is very often defined in another one,
    # and adding a second definition here would shadow it.
    for text in existing_texts:
        have |= _generated_tables(str(text or ""))
    missing = sorted(revisits - have)
    if not missing:
        return review_yaml
    parts = [review_yaml.rstrip("\n")]
    parts.extend(_FALLBACK_TABLE.format(name=name).rstrip("\n") for name in missing)
    return "\n---\n".join(parts) + "\n"


def sync_review_screen(source_yaml: str, review_yaml: str) -> Tuple[str, bool]:
    """Put ``review_yaml`` where the file's current review screen is.

    The review block is replaced in place, along with the revisit screens and
    tables the new draft actually regenerates -- leaving those behind would
    define the same block twice. Anything the draft does not regenerate is left
    alone: the author wrote it, not the Weaver, and a table the draft has no
    replacement for is still the one its revisit screen displays.

    Returns the new source and whether an existing review screen was replaced;
    when there was none, the draft is appended.
    """
    # Tracked apart on purpose. A draft can regenerate a list's revisit screen
    # without regenerating its table, and dropping the table anyway leaves the
    # new screen pointing at a `${ <list>.table }` that no longer exists.
    regenerated_tables = _generated_tables(review_yaml)
    regenerated_revisits = _generated_revisits(review_yaml)
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
        if name and name in regenerated_tables:
            drop.add(index)
            continue
        name = _list_name(parsed.get("continue button field"), ".revisit")
        if name and name in regenerated_revisits:
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
    from ruamel.yaml.scalarstring import LiteralScalarString

    yaml = YAML()
    yaml.default_flow_style = False
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.width = 4096
    documents = list(yaml.load_all(review_yaml))
    for document in documents:
        if not isinstance(document, dict) or "review" not in document:
            continue
        if screen_id:
            document["id"] = screen_id
        if event_name:
            document["event"] = event_name
        if question_text:
            # A literal block, not the quoted scalar with an escaped newline
            # ruamel would otherwise write: this is going back into a file an
            # author reads.
            document["question"] = LiteralScalarString(
                str(question_text).rstrip("\n") + "\n"
            )
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
