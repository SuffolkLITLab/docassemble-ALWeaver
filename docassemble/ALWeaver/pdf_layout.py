"""Read what a PDF prints, and what it prints around its fill-in boxes."""

import os
from collections import OrderedDict
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from pdfminer.high_level import extract_pages
from pdfminer.layout import LTChar, LTContainer, LTItem, LTText, LTTextBox
from pdfminer.pdfpage import PDFPage

__all__ = ["fields_after_a_dollar_sign", "pdf_text"]

# How far left of a box, and how far into it, a printed "$" still belongs to it.
# Checked against 202 money fields on real court forms; anything from 15 to 60
# points finds the same boxes.
_DOLLAR_REACH_LEFT = 20.0
_DOLLAR_REACH_INSIDE = 8.0
_SAME_LINE_SLACK = 3.0

Box = Tuple[float, float, float, float]


# Each recently read file's pages, by 1-based number: the page's text and
# where each "$" on it sits
_read_pages_cache: (
    "OrderedDict[Tuple[str, int, int], Dict[int, Tuple[str, List[Box]]]]"
) = OrderedDict()
_CACHED_FILES = 4


def _page_reading(layout: LTItem) -> Tuple[str, List[Box]]:
    """One page's text, written the way pdfminer's `extract_text()` writes it,
    and where each "$" on it sits."""
    parts: List[str] = []
    dollar_signs: List[Box] = []

    def render(item: LTItem) -> None:
        if isinstance(item, LTContainer):
            for child in item:
                render(child)
        elif isinstance(item, LTText):
            text = item.get_text()
            parts.append(text)
            if text == "$" and isinstance(item, LTChar):
                dollar_signs.append(item.bbox)
        if isinstance(item, LTTextBox):
            parts.append("\n")

    render(layout)
    parts.append("\f")
    return "".join(parts), dollar_signs


def _read_pages(
    path: str, page_numbers: Optional[Iterable[int]] = None
) -> Dict[int, Tuple[str, List[Box]]]:
    """Read the given 1-based pages, or all of them, each only once per file.

    Laying out a page is the slow part of reading a PDF (about 70 ms a page),
    and drafting reads the same pages for the "$" signs and for the form's
    text.
    """
    stat = os.stat(path)
    key = (os.path.abspath(path), stat.st_mtime_ns, stat.st_size)
    pages = _read_pages_cache.setdefault(key, {})
    _read_pages_cache.move_to_end(key)
    while len(_read_pages_cache) > _CACHED_FILES:
        _read_pages_cache.popitem(last=False)
    if page_numbers is None:
        with open(path, "rb") as handle:
            page_numbers = range(1, sum(1 for _ in PDFPage.get_pages(handle)) + 1)
    missing = sorted(set(page_numbers) - set(pages))
    if missing:
        for page_number, layout in zip(
            missing, extract_pages(path, page_numbers=[page - 1 for page in missing])
        ):
            pages[page_number] = _page_reading(layout)
    return pages


def pdf_text(path: str) -> str:
    """The PDF's text, the same as pdfminer's `extract_text()` gives."""
    pages = _read_pages(path)
    return "".join(pages[number][0] for number in sorted(pages))


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
    pages = _read_pages(path, (page for _name, page, _box in located))
    after_dollar: Set[str] = set()
    for name, page, box in located:
        x0, y0, _x1, y1 = (float(value) for value in box[:4])
        _text, signs = pages.get(page, ("", []))
        for sign_x0, sign_y0, sign_x1, sign_y1 in signs:
            middle = (sign_y0 + sign_y1) / 2
            if (
                y0 - _SAME_LINE_SLACK <= middle <= y1 + _SAME_LINE_SLACK
                and x0 - _DOLLAR_REACH_LEFT <= sign_x1 <= x0 + _DOLLAR_REACH_INSIDE
            ):
                after_dollar.add(name)
                break
    return after_dollar
