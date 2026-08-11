"""Deterministic literal search and replacement helpers for editor projects.

The browser never sends replacement text as an instruction to interpret.  It
sends exact source spans from a search response, and these helpers verify that
the spans are still matches before producing a new source buffer.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Sequence, Tuple

MAX_SEARCH_QUERY_CHARS = 500
MAX_REPLACEMENT_CHARS = 100_000
MAX_PROJECT_MATCHES = 2_000
MAX_MATCHES_PER_FILE = 500
CONTEXT_CHARS = 90


def compile_literal_pattern(
    query: str, *, case_sensitive: bool = False, whole_word: bool = False
) -> "re.Pattern[str]":
    """Compile a bounded, non-regex project-search pattern."""
    value = str(query or "")
    if not value:
        raise ValueError("Search text is required")
    if len(value) > MAX_SEARCH_QUERY_CHARS:
        raise ValueError(
            f"Search text may be at most {MAX_SEARCH_QUERY_CHARS} characters"
        )
    escaped = re.escape(value)
    if whole_word:
        escaped = rf"(?<!\w){escaped}(?!\w)"
    return re.compile(escaped, 0 if case_sensitive else re.IGNORECASE)


def context_for_span(source: str, start: int, end: int) -> Dict[str, Any]:
    """Return line/column and a small, single-line context around one span."""
    line_start = source.rfind("\n", 0, start) + 1
    line_end = source.find("\n", end)
    if line_end < 0:
        line_end = len(source)
    before = source[max(line_start, start - CONTEXT_CHARS) : start]
    matched = source[start:end]
    after = source[end : min(line_end, end + CONTEXT_CHARS)]
    return {
        "start": start,
        "end": end,
        "line": source.count("\n", 0, start) + 1,
        "column": start - line_start + 1,
        "before": before,
        "match": matched,
        "after": after,
        "before_truncated": start - line_start > CONTEXT_CHARS,
        "after_truncated": line_end - end > CONTEXT_CHARS,
    }


def find_literal_matches(
    source: str,
    query: str,
    *,
    case_sensitive: bool = False,
    whole_word: bool = False,
    limit: int = MAX_MATCHES_PER_FILE,
) -> Tuple[List[Dict[str, Any]], bool]:
    """Find literal matches and return contexts plus a truncation flag."""
    pattern = compile_literal_pattern(
        query, case_sensitive=case_sensitive, whole_word=whole_word
    )
    matches: List[Dict[str, Any]] = []
    truncated = False
    for match in pattern.finditer(source):
        if len(matches) >= limit:
            truncated = True
            break
        matches.append(context_for_span(source, match.start(), match.end()))
    return matches, truncated


def normalize_selected_spans(raw_spans: Iterable[Any]) -> List[Tuple[int, int]]:
    """Validate browser-provided source spans and reject overlaps."""
    spans: List[Tuple[int, int]] = []
    for raw in raw_spans:
        if not isinstance(raw, dict):
            raise ValueError("Each selected match must be an object")
        start = raw.get("start")
        end = raw.get("end")
        if isinstance(start, bool) or isinstance(end, bool):
            raise ValueError("Match offsets must be integers")
        if not isinstance(start, int) or not isinstance(end, int):
            raise ValueError("Match offsets must be integers")
        if start < 0 or end <= start:
            raise ValueError("Match offsets are invalid")
        spans.append((start, end))
    spans = sorted(set(spans))
    for previous, current in zip(spans, spans[1:]):
        if previous[1] > current[0]:
            raise ValueError("Selected matches may not overlap")
    return spans


def replace_selected_matches(
    source: str,
    query: str,
    replacement: str,
    raw_spans: Sequence[Any],
    *,
    case_sensitive: bool = False,
    whole_word: bool = False,
) -> Tuple[str, int]:
    """Replace only verified spans from a prior literal search."""
    if not isinstance(replacement, str):
        raise ValueError("Replacement must be text")
    if len(replacement) > MAX_REPLACEMENT_CHARS:
        raise ValueError(
            f"Replacement may be at most {MAX_REPLACEMENT_CHARS} characters"
        )
    spans = normalize_selected_spans(raw_spans)
    pattern = compile_literal_pattern(
        query, case_sensitive=case_sensitive, whole_word=whole_word
    )
    current_spans = {(match.start(), match.end()) for match in pattern.finditer(source)}
    missing = [span for span in spans if span not in current_spans]
    if missing:
        raise ValueError("One or more selected matches no longer match the search")

    updated = source
    for start, end in reversed(spans):
        updated = updated[:start] + replacement + updated[end:]
    return updated, len(spans)
