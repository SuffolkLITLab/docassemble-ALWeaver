"""Deterministic repair of the blocking problems that are purely mechanical.

Two DAYamlChecker errors dominate real interviews: a question block with no
``id``, and two blocks sharing one. Both are genuine problems and both have a
single obvious fix, so refusing to start the assistant over them just makes a
developer do clerical work by hand.

Nothing here involves a model. Repairs are computed from the parsed source,
applied as exact range patches, and kept only if the whole candidate comes back
no worse than it started. Every change is reported so it shows up in the diff
the developer reviews before saving.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .editor_agent_validation import (
    CandidateValidation,
    lint_level_from_severity,
    validate_candidate_source,
)
from .source_document import (
    apply_range_operations,
    document_content_offset,
    parse_source_document,
)

REPAIR_MISSING_ID = "missing_id"
REPAIR_DUPLICATE_ID = "duplicate_id"

# Matched against DAYamlChecker's own wording so the count offered to a
# developer ("fix 3 problems") is never larger than what is actually fixable.
_MISSING_ID_PATTERN = re.compile(r"block is missing an .?id", re.IGNORECASE)
_DUPLICATE_ID_PATTERN = re.compile(r"duplicate block id", re.IGNORECASE)

MAX_REPAIR_PASSES = 3
MAX_GENERATED_ID_LENGTH = 48


@dataclass
class SourceRepair:
    """One mechanical change, in terms a developer can check against the diff."""

    kind: str
    new_id: str
    line_start: Optional[int]
    summary: str
    previous_id: Optional[str] = None

    def public_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "new_id": self.new_id,
            "previous_id": self.previous_id,
            "line_start": self.line_start,
            "summary": self.summary,
        }


@dataclass
class RepairResult:
    raw_yaml: str
    repairs: List[SourceRepair] = field(default_factory=list)
    validation: Optional[CandidateValidation] = None
    remaining_blocking: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.repairs)

    @property
    def healed(self) -> bool:
        """True when nothing blocking is left after the repairs."""
        return not self.remaining_blocking

    def public_dict(self) -> Dict[str, Any]:
        return {
            "repairs": [item.public_dict() for item in self.repairs],
            "repair_count": len(self.repairs),
            "healed": self.healed,
            "remaining_diagnostics": self.remaining_blocking,
        }


def classify_diagnostics(
    diagnostics: Sequence[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split blocking diagnostics into the mechanical ones and the rest."""
    repairable: List[Dict[str, Any]] = []
    remaining: List[Dict[str, Any]] = []
    for diagnostic in diagnostics:
        level = lint_level_from_severity(
            diagnostic.get("level") or diagnostic.get("severity")
        )
        if level != "error":
            continue
        message = str(diagnostic.get("message") or "")
        if _MISSING_ID_PATTERN.search(message) or _DUPLICATE_ID_PATTERN.search(message):
            repairable.append(diagnostic)
        else:
            remaining.append(diagnostic)
    return repairable, remaining


def _slugify(text: Any, fallback: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", str(text or "")).strip("_").lower()
    slug = re.sub(r"_+", "_", slug)[:MAX_GENERATED_ID_LENGTH].strip("_")
    if not slug:
        return fallback
    if slug[0].isdigit():
        slug = f"screen_{slug}"
    return slug


def _unique(candidate: str, taken: set) -> str:
    if candidate not in taken:
        return candidate
    suffix = 2
    while f"{candidate}_{suffix}" in taken:
        suffix += 1
    return f"{candidate}_{suffix}"


def _plan_repairs(
    filename: str, raw_yaml: str
) -> Tuple[List[Dict[str, Any]], List[SourceRepair]]:
    """Compute the range operations that fix ids, without applying them."""
    from .editor_utils import parse_interview_yaml

    model = parse_interview_yaml(raw_yaml)
    document = parse_source_document(filename, raw_yaml)
    source_blocks = {item.document_index: item for item in document.documents}

    blocks = model.get("blocks", [])
    taken = {
        str(block["data"]["id"])
        for block in blocks
        if isinstance(block.get("data"), dict) and block["data"].get("id")
    }

    operations: List[Dict[str, Any]] = []
    repairs: List[SourceRepair] = []
    seen_ids: set = set()

    for position, block in enumerate(blocks, start=1):
        source_block = source_blocks.get(block.get("index"))
        # Never touch source Weaver cannot represent losslessly.
        if source_block is None or not source_block.supported:
            continue
        data = block.get("data")
        if not isinstance(data, dict):
            continue

        explicit_id = data.get("id")
        if explicit_id is None:
            # DAYamlChecker only requires an id on question-bearing blocks.
            if "question" not in data:
                continue
            title = re.sub(r"\s+", " ", str(block.get("title") or "")).strip()
            new_id = _unique(_slugify(title, f"screen_{position}"), taken)
            taken.add(new_id)
            seen_ids.add(new_id)
            insert_at = source_block.start_offset + document_content_offset(
                source_block.raw_text
            )
            operations.append(
                {
                    "type": "replace-range",
                    "start": insert_at,
                    "end": insert_at,
                    "text": f"id: {new_id}\n",
                }
            )
            repairs.append(
                SourceRepair(
                    kind=REPAIR_MISSING_ID,
                    new_id=new_id,
                    line_start=block.get("line_start"),
                    summary=f"Gave the screen “{title}” the id {new_id}.",
                )
            )
            continue

        current_id = str(explicit_id)
        if current_id not in seen_ids:
            seen_ids.add(current_id)
            continue

        id_range = source_block.property_ranges.get("id")
        if id_range is None:
            # No addressable `id:` value means no safe mechanical rename.
            continue
        new_id = _unique(current_id, taken)
        taken.add(new_id)
        seen_ids.add(new_id)
        operations.append(
            {
                "type": "replace-range",
                "start": id_range.start.offset,
                "end": id_range.end.offset,
                "text": new_id,
            }
        )
        repairs.append(
            SourceRepair(
                kind=REPAIR_DUPLICATE_ID,
                new_id=new_id,
                previous_id=current_id,
                line_start=block.get("line_start"),
                summary=(
                    f"Renamed the repeated id {current_id} to {new_id}. Docassemble "
                    f"was silently using only the last block called {current_id}; "
                    "both are reachable now, so check this block still belongs."
                ),
            )
        )

    return operations, repairs


def auto_heal_source(*, filename: str, raw_yaml: str) -> RepairResult:
    """Fix mechanical id problems, or report honestly that it could not.

    A repair pass is only kept when it leaves strictly fewer blocking
    diagnostics than it started with, so a repair can never make a file worse
    than the developer handed over.
    """
    current = raw_yaml
    validation = validate_candidate_source(filename=filename, raw_yaml=current)
    repairs: List[SourceRepair] = []

    for _pass in range(MAX_REPAIR_PASSES):
        blocking_before = len(validation.blocking_diagnostics())
        if not blocking_before:
            break
        operations, pass_repairs = _plan_repairs(filename, current)
        if not operations:
            break
        try:
            proposed, _applied = apply_range_operations(current, operations)
        except ValueError:
            break
        proposed_validation = validate_candidate_source(
            filename=filename, raw_yaml=proposed
        )
        if len(proposed_validation.blocking_diagnostics()) >= blocking_before:
            break
        current = proposed
        validation = proposed_validation
        repairs.extend(pass_repairs)

    return RepairResult(
        raw_yaml=current,
        repairs=repairs,
        validation=validation,
        remaining_blocking=validation.blocking_diagnostics(),
    )


def describe_repair_offer(*, filename: str, raw_yaml: str) -> Dict[str, Any]:
    """Preview what auto-heal would do, without changing anything.

    Used to tell a developer "3 of these 4 errors can be fixed automatically"
    before they decide whether to let it happen.
    """
    validation = validate_candidate_source(filename=filename, raw_yaml=raw_yaml)
    blocking = validation.blocking_diagnostics()
    repairable, unrepairable = classify_diagnostics(blocking)
    preview = auto_heal_source(filename=filename, raw_yaml=raw_yaml)
    return {
        "diagnostics": blocking,
        "repairable_count": len(repairable),
        "unrepairable_count": len(unrepairable),
        "can_auto_heal": bool(preview.repairs) and preview.healed,
        "repairs": [item.public_dict() for item in preview.repairs],
    }
