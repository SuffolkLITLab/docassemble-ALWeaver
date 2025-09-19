# extract_vars.py  – drop-in replacement
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Set, Union

from docx2python import docx2python
from jinja2 import Environment, nodes
from jinja2.visitor import NodeVisitor

__all__ = ["extract_docx_vars", "extract_docx_filtered_vars"]


# ---------------------------------------------------------------------------
# 1.  AST visitor
# ---------------------------------------------------------------------------
class TemplateVarVisitor(NodeVisitor):
    """Collect variable paths and resolve aliases created by {% for … %}."""

    # IMPLICIT_ATTRS: Set[str] = {}

    IGNORE_ROOTS: Set[str] = {
        "loop",
        "cycler",
        "namespace",
        "include_docx_template",
        "comma_and_list",
        "nice_number",
        "state_name",
        "defined",
        "showifdef",
    }

    def __init__(self, *, keep_calls: bool = False) -> None:
        super().__init__()
        self.keep_calls = keep_calls
        self._loop_stack: List[Dict[str, str]] = []
        self.results: Set[str] = set()

    # --- visitors ----------------------------------------------------------
    def visit_For(self, node: nodes.For, /) -> None:
        targets = self._targets(node.target)
        iter_expr = self._expr_to_str(node.iter)
        self._loop_stack.append({t: iter_expr for t in targets})
        self.generic_visit(node)
        self._loop_stack.pop()

    def visit_Getattr(self, node: nodes.Getattr, /) -> None:
        chain = self._chain(node)
        root = self._resolve(chain[0])
        if chain[0] in self.IGNORE_ROOTS:
            return
        full = ".".join([root, *chain[1:]])
        # if chain[-1] not in self.IMPLICIT_ATTRS:
        self.results.add(full)
        self.generic_visit(node)

    def visit_Name(self, node: nodes.Name, /) -> None:
        if node.name in self.IGNORE_ROOTS:
            return
        self.results.add(self._resolve(node.name))

    def visit_Call(self, node: nodes.Call, /) -> None:
        """
        When keep_calls is True, record the call with '()' *and* make sure the
        loop-alias rewriting (executor ➜ x.executors[i]) is applied.
        """
        # Always walk inside the call so we capture arguments too
        self.generic_visit(node)

        if not self.keep_calls:
            return

        # String form without alias replacement yet
        callee = self._expr_to_str(node.node)  # 'executor.appointment.name_full'
        parts = callee.split(".")
        root, rest = parts[0], parts[1:]

        if root in self.IGNORE_ROOTS:  # skip loop.index, etc.
            return

        resolved_root = self._resolve(root)  # 'executor' ➜ 'x.executors[i]'
        full_call = ".".join([resolved_root, *rest]) + "()"  # add the ()

        self.results.add(full_call)

    # --- helpers -----------------------------------------------------------
    @staticmethod
    def _targets(t: nodes.Node) -> List[str]:
        if isinstance(t, nodes.Name):
            return [t.name]
        if isinstance(t, nodes.Tuple):
            names: List[str] = []
            for item in t.items:
                names.extend(TemplateVarVisitor._targets(item))
            return names
        return []

    def _resolve(self, name: str) -> str:
        # Extract base name from indexed variables for loop resolution
        base_name = name.split("[")[0] if "[" in name else name

        for mapping in reversed(self._loop_stack):
            if base_name in mapping:
                # If the original name had an explicit index, preserve it
                if "[" in name:
                    return name  # Keep explicit indices like clients[0]
                else:
                    return f"{mapping[base_name]}[i]"  # Convert to loop variable
        return name

    @staticmethod
    def _expr_to_str(expr: nodes.Node) -> str:
        """
        Return a human-readable string for the *iterable* side of a {% for … %}
        so alias resolution works. Handles:
          • plain names           →  people
          • dotted chains         →  x.executors
          • sub-scripts / slices  →  x.executors   (strip “[2:]”, “[i]”, …)
          • calls / filters       →  base expr
        """
        if isinstance(expr, nodes.Name):
            return expr.name
        if isinstance(expr, nodes.Getattr):
            return ".".join(TemplateVarVisitor._chain(expr))

        # peel off x[...] or x[2:]
        if isinstance(expr, nodes.Getitem):  # Jinja ≤3.x
            return TemplateVarVisitor._expr_to_str(expr.node)
        # safety for potential Slice node variants
        if hasattr(nodes, "Slice") and isinstance(expr, nodes.Slice):
            # Try different attribute names for different Jinja versions
            for attr in ["value", "node", "obj"]:
                if hasattr(expr, attr):
                    slice_val = getattr(expr, attr)
                    if slice_val:
                        return TemplateVarVisitor._expr_to_str(slice_val)

        # calls / filters
        if isinstance(expr, nodes.Call):
            if expr.node:
                return TemplateVarVisitor._expr_to_str(expr.node)
        if isinstance(expr, nodes.Filter):
            if expr.node:
                return TemplateVarVisitor._expr_to_str(expr.node)

        return "<expr>"

    # ─────────────────────────────────────────────────────────────────────
    @staticmethod
    def _chain(node: nodes.Node) -> List[str]:
        """
        Build ['x', 'executors', 'appointment'] from x.executors.appointment
        or ['x', 'executors[0]', 'appointment'] from x.executors[0].appointment
        to preserve explicit array indices while still handling attribute chains.
        """
        parts: List[str] = []
        while True:
            if isinstance(node, nodes.Getattr):
                parts.insert(0, node.attr)
                node = node.node
            # Preserve explicit indices in variable names (like clients[0])
            elif isinstance(node, nodes.Getitem):
                # Get the index/slice part - different Jinja versions have different structures
                slice_node = getattr(node, "slice", getattr(node, "arg", None))
                if slice_node:
                    if hasattr(slice_node, "value"):  # nodes.Const in newer Jinja
                        index_val = slice_node.value
                    elif hasattr(slice_node, "n"):  # nodes.Num in older versions
                        index_val = slice_node.n
                    else:
                        # For complex slices or variables, fall back to original behavior
                        node = node.node
                        continue

                    # Get the base variable name
                    base_parts = TemplateVarVisitor._chain(node.node)
                    if base_parts:
                        # Combine the base name with the index: clients[0] instead of just clients
                        base_parts[-1] = f"{base_parts[-1]}[{index_val}]"
                        return base_parts + parts
                node = node.node
            else:
                break
        if isinstance(node, nodes.Name):
            parts.insert(0, node.name)
        return parts


class TemplateFilteredVarVisitor(NodeVisitor):
    """Collect variables that use a specific filter (like if_final)."""

    IGNORE_ROOTS: Set[str] = {
        "loop",
        "cycler",
        "namespace",
        "include_docx_template",
        "comma_and_list",
        "nice_number",
        "state_name",
        "defined",
        "showifdef",
    }

    def __init__(self, filter_name: str = "if_final") -> None:
        super().__init__()
        self.filter_name = filter_name
        self._loop_stack: List[Dict[str, str]] = []
        self.results: Set[str] = set()

    # --- visitors ----------------------------------------------------------
    def visit_For(self, node: nodes.For, /) -> None:
        targets = TemplateVarVisitor._targets(node.target)
        iter_expr = TemplateVarVisitor._expr_to_str(node.iter)
        self._loop_stack.append({t: iter_expr for t in targets})
        self.generic_visit(node)
        self._loop_stack.pop()

    def visit_Filter(self, node: nodes.Filter, /) -> None:
        """Visit filter expressions like {{ var | if_final }}"""
        # Check if this filter matches our target filter name
        if node.name == self.filter_name:
            # Extract the variable being filtered
            if node.node:  # Check that node.node is not None
                var_expr = self._extract_variable_from_node(node.node)
                if var_expr and not self._should_ignore_variable(var_expr):
                    self.results.add(var_expr)

        # Continue visiting child nodes
        self.generic_visit(node)

    def _extract_variable_from_node(self, node: nodes.Node) -> str:
        """Extract variable path from a node, handling various node types."""
        if isinstance(node, nodes.Name):
            return self._resolve(node.name)
        elif isinstance(node, nodes.Getattr):
            chain = TemplateVarVisitor._chain(node)
            root = self._resolve(chain[0])
            return ".".join([root, *chain[1:]])
        elif isinstance(node, nodes.Getitem):
            # Handle indexed variables like clients[0]
            chain = TemplateVarVisitor._chain(node)
            if chain:
                root = self._resolve(chain[0])
                return ".".join([root, *chain[1:]])
        elif isinstance(node, nodes.Call):
            # Handle method calls
            callee = TemplateVarVisitor._expr_to_str(node.node)
            parts = callee.split(".")
            root, rest = parts[0], parts[1:]
            resolved_root = self._resolve(root)
            return ".".join([resolved_root, *rest])

        return ""

    def _should_ignore_variable(self, var_path: str) -> bool:
        """Check if variable should be ignored based on IGNORE_ROOTS."""
        root = var_path.split(".")[0].split("[")[0]  # Handle both dots and brackets
        return root in self.IGNORE_ROOTS

    def _resolve(self, name: str) -> str:
        """Resolve loop aliases, same logic as TemplateVarVisitor."""
        base_name = name.split("[")[0] if "[" in name else name

        for mapping in reversed(self._loop_stack):
            if base_name in mapping:
                if "[" in name:
                    return name  # Keep explicit indices
                else:
                    return f"{mapping[base_name]}[i]"
        return name


# ---------------------------------------------------------------------------
# 2.  Docassemble / python-docx-template quirks  ➜  simple text re-write
# ---------------------------------------------------------------------------
# All custom block prefixes we need to neutralize:
_PREFIXES = ("p", "tr", "tc", "tbl", "r", "sectPr")
_BLOCK_PREFIX_RX = re.compile(
    r"\{%\s*(?:" + "|".join(_PREFIXES) + r")\b", re.IGNORECASE
)

_EXPR_PREFIX_RX = re.compile(
    r"(\{\{\s*)(?:" + "|".join(_PREFIXES) + r")\s+", re.IGNORECASE
)


def _normalize_docxtpl_blocks(text: str) -> str:
    """Remove custom prefixes + straighten smart quotes."""
    text = _BLOCK_PREFIX_RX.sub("{%", text)  # {%p …%} ➜ {% …%}
    text = _EXPR_PREFIX_RX.sub(r"\1", text)  # {{p …}} ➜ {{ …}}

    # Replace “smart” quotes with straight ones so Jinja can parse strings
    text = text.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    return text


# ---------------------------------------------------------------------------
# 3.  Public helper
# ---------------------------------------------------------------------------
def extract_docx_vars(
    docx_path: Union[str, Path], *, keep_calls: bool = False
) -> Set[str]:
    """
    • `keep_calls=False` (default)  →  'x.spouse.name_full'
    • `keep_calls=True`            →  'x.spouse.name_full()'
    """
    docx_path = Path(docx_path)

    # 1. pull template text
    with docx2python(docx_path) as doc:
        raw = doc.text

    # 2. normalise custom block prefixes
    cleaned = _normalize_docxtpl_blocks(raw)

    # 3. parse & visit
    ast = Environment().parse(cleaned)
    visitor = TemplateVarVisitor(keep_calls=keep_calls)
    visitor.visit(ast)

    if keep_calls:
        calls_with_paren = {v[:-2] for v in visitor.results if v.endswith("()")}
        visitor.results.difference_update(calls_with_paren)
    return visitor.results


def extract_docx_filtered_vars(
    docx_path: Union[str, Path], *, filter_name: str = "if_final"
) -> Set[str]:
    """
    Extract variables that use a specific filter from a DOCX template.

    Args:
        docx_path: Path to the DOCX file
        filter_name: Name of the filter to look for (default: "if_final")

    Returns:
        Set of variable paths that use the specified filter

    Example:
        For template containing: {{ some_variable.signature | if_final }}
        Returns: {'some_variable.signature'}
    """
    docx_path = Path(docx_path)

    # 1. pull template text
    with docx2python(docx_path) as doc:
        raw = doc.text

    # 2. normalise custom block prefixes
    cleaned = _normalize_docxtpl_blocks(raw)

    # 3. parse & visit
    ast = Environment().parse(cleaned)
    visitor = TemplateFilteredVarVisitor(filter_name=filter_name)
    visitor.visit(ast)

    return visitor.results
