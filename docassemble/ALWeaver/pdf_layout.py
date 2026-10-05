"""Read what a PDF prints around its fill-in boxes."""

from collections import defaultdict
from typing import Any, Dict, Iterable, List, Sequence, Set, Tuple

from pdfminer.high_level import extract_pages
from pdfminer.layout import LTChar

__all__ = ["fields_after_a_dollar_sign"]

# How far left of a box, and how far into it, a printed "$" still belongs to it.
# Checked against 202 money fields on real court forms; anything from 15 to 60
# points finds the same boxes.
_DOLLAR_REACH_LEFT = 20.0
_DOLLAR_REACH_INSIDE = 8.0
_SAME_LINE_SLACK = 3.0

Box = Tuple[float, float, float, float]


def _dollar_signs(path: str, pages: Iterable[int]) -> Dict[int, List[Box]]:
    """Where each "$" sits on the given 1-based pages."""
    wanted = sorted(set(pages))
    found: Dict[int, List[Box]] = defaultdict(list)
    for page_number, layout in zip(
        wanted, extract_pages(path, page_numbers=[page - 1 for page in wanted])
    ):
        stack: List[Any] = [layout]
        while stack:
            item = stack.pop()
            if isinstance(item, LTChar):
                if item.get_text() == "$":
                    found[page_number].append(item.bbox)
            elif hasattr(item, "__iter__"):
                stack.extend(item)
    return found


def fields_after_a_dollar_sign(
    path: str, fields: Sequence[Tuple[str, int, Sequence[float]]]
) -> Set[str]:
    """The fields whose box the PDF already prints a "$" in front of.

    Filling one of those with `currency()` prints "$ $1,200.00", which is what
    authors avoid by writing `thousands()` instead.

    Args:
        path (str): the PDF file.
        fields (Sequence[Tuple[str, int, Sequence[float]]]): each field's
            name, 1-based page and `[x0, y0, x1, y1]` box.

    Returns:
        Set[str]: the names of the fields with a "$" printed just before them.
    """
    located = [
        (name, page, box)
        for name, page, box in fields
        if page and box and len(box) >= 4
    ]
    if not located:
        return set()
    signs = _dollar_signs(path, (page for _name, page, _box in located))
    after_dollar: Set[str] = set()
    for name, page, box in located:
        x0, y0, _x1, y1 = (float(value) for value in box[:4])
        for sign_x0, sign_y0, sign_x1, sign_y1 in signs.get(page, []):
            middle = (sign_y0 + sign_y1) / 2
            if (
                y0 - _SAME_LINE_SLACK <= middle <= y1 + _SAME_LINE_SLACK
                and x0 - _DOLLAR_REACH_LEFT <= sign_x1 <= x0 + _DOLLAR_REACH_INSIDE
            ):
                after_dollar.add(name)
                break
    return after_dollar
