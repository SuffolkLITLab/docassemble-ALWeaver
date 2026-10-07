"""Static, source-addressable interview inventory shared by editor reports.

No interview Python or Mako is evaluated. Reachability is deliberately a hint:
external modules and dynamically constructed variable names can add dependencies.
"""

import ast
import re
from typing import Any, Callable, Dict, List, Set

from .editor_utils import parse_interview_yaml, parse_order_code, source_revision

FIELD_OPTIONS = {
    "label",
    "field",
    "datatype",
    "required",
    "default",
    "default code",
    "hint",
    "help",
    "note",
    "html",
    "raw html",
    "code",
    "choices",
    "choices code",
    "shuffle",
    "show if",
    "hide if",
    "disable others",
    "uncheck others",
    "none of the above",
    "minlength",
    "maxlength",
    "min",
    "max",
    "step",
    "validate",
    "validation messages",
    "css class",
    "label above field",
    "grid",
    "rows",
    "address autocomplete",
    "disable autocomplete",
    "input type",
    "accept",
    "capture",
    "sign",
    "saveas",
    "under text",
    "floating label",
    "ml group",
    "object label",
    "exclude",
}
FIELD_OPTIONS.update(
    {
        "validation code",
        "raw label",
        "using",
        "keep for training",
        "maximum image size",
        "image upload type",
        "file css class",
        "allow privileges",
        "allow users",
        "persistent",
        "private",
        "object labeler",
        "help generator",
        "image generator",
        "disabled",
        "js show if",
        "js hide if",
        "js disable if",
        "js enable if",
        "disable if",
        "enable if",
        "check others",
        "item grid",
        "action",
        "trigger at",
        "field metadata",
        "scale",
        "inline",
        "inline width",
        "currency symbol",
        "group",
        "all of the above",
    }
)
DEFINITIONS = (
    "field",
    "continue button field",
    "yesno",
    "noyes",
    "yesnomaybe",
    "noyesmaybe",
    "signature",
    "sets",
    "event",
    "template",
    "table",
)


def _strings(value: Any) -> List[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str)]
    return []


def _names(code: str) -> tuple[Set[str], Set[str]]:
    """Read both full attribute paths and roots; never execute source."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return set(), set()
    reads: Set[str] = set()
    writes: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Name, ast.Attribute, ast.Subscript)):
            name = ast.unparse(node)
            (writes if isinstance(node.ctx, ast.Store) else reads).add(name)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in {
                "defined",
                "showifdef",
                "value",
                "force_ask",
                "force_gather",
            }:
                reads.update(
                    arg.value
                    for arg in node.args
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                )
    # Function parameters and method locals are not interview variables.
    local_writes: Set[str] = set()
    declarations: Set[str] = set()
    for statement in tree.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            declarations.add(statement.name)
            for child in ast.walk(statement):
                if isinstance(
                    child, (ast.Name, ast.Attribute, ast.Subscript)
                ) and isinstance(child.ctx, ast.Store):
                    local_writes.add(ast.unparse(child))
    module_writes: Set[str] = set()
    for statement in tree.body:
        if not isinstance(
            statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            for child in ast.walk(statement):
                if isinstance(
                    child, (ast.Name, ast.Attribute, ast.Subscript)
                ) and isinstance(child.ctx, ast.Store):
                    module_writes.add(ast.unparse(child))
    return reads, (writes - local_writes) | module_writes | declarations


def _mako_uses(text: str) -> tuple[Set[str], Set[str]]:
    """Read expression and control-line names and whole-object uses with Mako's parser."""
    from mako.lexer import Lexer

    if "${" not in text and not re.search(r"^\s*%", text, re.M):
        return set(), set()
    try:
        tree = Lexer(text).parse()
    except Exception:
        return set(), set()
    reads: Set[str] = set()
    receivers: Set[str] = set()
    seen: Set[int] = set()
    pending = list(tree.get_children())
    while pending:
        node = pending.pop()
        if id(node) in seen:
            continue
        seen.add(id(node))
        expression = getattr(node, "text", "")
        if type(node).__name__ == "Expression":
            reads.update(_names(expression.strip())[0])
            receivers.update(_receivers(expression.strip()))
        elif type(node).__name__ == "ControlLine" and not node.isend:
            if node.keyword == "elif":
                expression = "if" + expression[4:]
            reads.update(_names(expression + "\n    pass")[0])
            receivers.update(_receivers(expression + "\n    pass"))
        pending.extend(node.get_children())
    return reads, receivers


# Reading one of these attributes asks Docassemble to gather the whole object.
GATHER_ATTRIBUTES = {
    "gather",
    "gathered",
    "complete",
    "complete_elements",
    "gathered_and_complete",
    "auto_gather",
    "number",
    "number_gathered",
}


def _receivers(code: str) -> Set[str]:
    """Objects used whole: their attributes may be asked for indirectly.

    ``users.gather()`` asks for each element's attributes, ``users[0].name.full()``
    reads the name's parts, and ``for item in items`` or ``${ users }`` can do the
    same through ``__iter__`` or ``__str__``. Which attributes is decided by the
    object's class at runtime, so a receiver stands for all of them.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return set()
    result: Set[str] = set()
    chain = (ast.Name, ast.Attribute, ast.Subscript)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, chain):
                result.add(ast.unparse(node.func.value))
        elif isinstance(node, ast.Attribute) and node.attr in GATHER_ATTRIBUTES:
            if isinstance(node.value, chain):
                result.add(ast.unparse(node.value))
        elif isinstance(node, (ast.For, ast.comprehension)):
            if isinstance(node.iter, chain):
                result.add(ast.unparse(node.iter))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            # Formatting helpers that turn an object into text.
            if node.func.id in {"str", "len", "comma_and_list", "noun_plural"}:
                result.update(ast.unparse(a) for a in node.args if isinstance(a, chain))
    if len(tree.body) == 1 and isinstance(tree.body[0], ast.Expr):
        if isinstance(tree.body[0].value, chain):
            result.add(ast.unparse(tree.body[0].value))
    return result


def _key(name: str) -> str:
    return re.sub(r"\[[^\]]*\]", "[]", name.strip())


def _is_main_order(block: Dict[str, Any]) -> bool:
    data = block.get("data") or {}
    return isinstance(data.get("code"), str) and bool(
        re.match(r"^main[ _]order(?:\b|_)", str(data.get("id", "")), re.I)
    )


def resolve_report_entrypoint(
    read_file: Callable[[str], str], filename: str, project_files: List[str]
) -> str:
    """Find a unique local main-order wrapper for an open reusable interview."""
    models = {filename: parse_interview_yaml(read_file(filename))["blocks"]}
    if any(_is_main_order(block) for block in models[filename]):
        return filename
    parents: Dict[str, Set[str]] = {}
    for name in project_files:
        if name not in models:
            try:
                models[name] = parse_interview_yaml(read_file(name))["blocks"]
            except (OSError, ValueError):
                continue
        for block in models[name]:
            for target in _strings((block.get("data") or {}).get("include")):
                if ":" not in target:
                    parents.setdefault(target, set()).add(name)
    ancestors: Set[str] = set()
    pending = list(parents.get(filename, set()))
    while pending:
        parent = pending.pop()
        if parent == filename or parent in ancestors:
            continue
        ancestors.add(parent)
        pending.extend(parents.get(parent, set()))
    candidates = sorted(
        name for name in ancestors if any(_is_main_order(b) for b in models[name])
    )
    if len(candidates) > 1:
        raise ValueError(
            "This file has multiple main-order entrypoints: "
            + ", ".join(candidates)
            + ". Open the standalone interview you want to report."
        )
    return candidates[0] if candidates else filename


def expand_report_steps(
    steps: List[Dict[str, Any]], named: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Expand child orders and legacy completion aliases without evaluating them."""

    def expand(items: List[Dict[str, Any]], active: tuple) -> List[Dict[str, Any]]:
        output = []
        for step in items:
            name = step.get("invoke") if step.get("kind") == "screen" else None
            if name in named and name not in active and len(active) < 40:
                output.extend(expand(named[name], active + (name,)))
            elif step.get("kind") in {"condition", "loop"}:
                output.append(
                    dict(
                        step,
                        children=expand(step.get("children", []), active),
                        else_children=expand(step.get("else_children", []), active),
                    )
                )
            else:
                output.append(step)
        return output

    return expand(steps, ())


def _screen_order(
    steps: List[Dict[str, Any]], blocks: List[Dict[str, Any]]
) -> List[str]:
    definitions: Dict[str, str] = {}
    for block in blocks:
        if "question" not in block.get("data", {}):
            continue
        for name in block.get("defines", []):
            definitions.setdefault(_key(name), block["scan_id"])
    result: List[str] = []

    def visit(items: List[Dict[str, Any]]) -> None:
        for step in items:
            target = step.get("source_block") or definitions.get(
                _key(step.get("invoke", ""))
            )
            if target and target not in result:
                result.append(target)
            visit(step.get("children", []))
            visit(step.get("else_children", []))

    visit(steps)
    return result


def _report_literals(blocks: List[Dict[str, Any]]) -> Dict[str, str]:
    """Only known display constants; never infer values from arbitrary Python."""
    result: Dict[str, str] = {}
    seen: Set[str] = set()
    for block in blocks:
        data = block.get("data") or {}
        if (
            "interview_short_title" not in seen
            and data.get("template") == "interview_short_title"
            and isinstance(data.get("content"), str)
        ):
            if "${" not in data["content"] and not re.search(
                r"^\s*%", data["content"], re.M
            ):
                result.setdefault("interview_short_title", data["content"].strip())
            seen.add("interview_short_title")
        try:
            tree = ast.parse(data.get("code", ""))
        except (SyntaxError, TypeError):
            continue
        for node in tree.body:
            value: Any
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target, value = node.targets[0], node.value
            elif isinstance(node, ast.AnnAssign):
                target, value = node.target, node.value
            else:
                continue
            if isinstance(target, ast.Name) and target.id in {
                "interview_short_title",
                "AL_ORGANIZATION_TITLE",
            }:
                if target.id not in seen:
                    if isinstance(value, ast.Constant) and isinstance(value.value, str):
                        result.setdefault(target.id, value.value)
                    seen.add(target.id)
    return result


def _symbols(blocks: List[Dict[str, Any]], package: str = "") -> List[Dict[str, Any]]:
    """Describe declarations without importing or executing interview code."""
    from .editor_function_catalog import _module_source_functions

    result: List[Dict[str, Any]] = []
    for block in blocks:
        data = block.get("data") or {}
        for directive in ("modules", "imports"):
            for module in _strings(data.get(directive)):
                if module.startswith("."):
                    origin = (
                        block["sourceFile"].split(":", 1)[0]
                        if ":" in block["sourceFile"]
                        else package
                    )
                    if not origin:
                        continue
                    module = origin + module
                for info in _module_source_functions(
                    module, directive == "imports", include_methods=True
                ).values():
                    result.append(
                        dict(
                            name=info["name"],
                            kind=info.get("kind", "function"),
                            signature=info["signature"],
                            documentation=info["doc"],
                            origin=module,
                            definitions=[block["scan_id"]],
                        )
                    )
        for kind in ("template", "table", "event"):
            for name in _strings(data.get(kind)):
                result.append(
                    dict(name=name, kind=kind, definitions=[block["scan_id"]])
                )
        try:
            tree = ast.parse(data.get("code", ""))
        except (SyntaxError, TypeError):
            continue

        def visit(nodes: List[Any], prefix: str = "", in_class: bool = False) -> None:
            for node in nodes:
                if isinstance(
                    node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                ):
                    name = prefix + node.name
                    kind = (
                        "class"
                        if isinstance(node, ast.ClassDef)
                        else "method" if in_class else "function"
                    )
                    result.append(
                        dict(
                            name=name,
                            kind=kind,
                            definitions=[block["scan_id"]],
                            signature=name
                            + (
                                "(" + ast.unparse(node.args) + ")"
                                if hasattr(node, "args")
                                else ""
                            ),
                            documentation=ast.get_docstring(node) or "",
                        )
                    )
                    if isinstance(node, ast.ClassDef):
                        visit(node.body, name + ".", True)

        visit(tree.body)
    unique: Dict[tuple[str, str], Dict[str, Any]] = {}
    for symbol in result:
        key = (symbol["kind"], symbol["name"])
        if key not in unique:
            unique[key] = symbol
        else:
            for definition in symbol["definitions"]:
                if definition not in unique[key]["definitions"]:
                    unique[key]["definitions"].append(definition)
    return list(unique.values())


def _boundary_suffixes(key: str) -> List[str]:
    """``users[].name.first`` -> ``[].name.first``, ``.name.first``, ``.first``."""
    return [key[i:] for i in range(1, len(key)) if key[i] in ".["]


class _DefinitionIndex:
    """Match read names to defined names, including generic ``x.`` blocks."""

    def __init__(self) -> None:
        self.names: Set[str] = set()
        self.generic: Dict[str, Set[str]] = {}

    def add(self, key: str, generic: bool) -> None:
        self.names.add(key)
        if generic and re.match(r"x[.\[]", key):
            self.generic.setdefault(key[1:], set()).add(key)

    def read(self, key: str) -> Set[str]:
        """Defined names that answer exactly this read."""
        found = {key} & self.names
        for suffix in _boundary_suffixes(key):
            found.update(self.generic.get(suffix, ()))
        return found

    def receiver(self, key: str) -> Set[str]:
        """Defined names for any attribute of an object used whole."""
        found = self.read(key)
        found.update(
            name
            for name in self.names
            if name.startswith(key) and name[len(key) : len(key) + 1] in {".", "["}
        )
        # Without the object's class, any generic attribute question may apply.
        for names in self.generic.values():
            found.update(names)
        return found


def scan_interview(
    read_file: Callable[[str], str],
    filename: str,
    max_files: int = 100,
    package: str = "",
) -> Dict[str, Any]:
    """Follow includes and retain source identities, definitions and references."""
    files: Dict[str, str] = {}
    blocks: List[Dict[str, Any]] = []
    warnings: List[str] = []
    pending = [filename]
    seen: Set[str] = set()
    while pending:
        name = pending.pop(0)
        if name in seen:
            continue
        seen.add(name)
        if len(seen) > max_files:
            warnings.append("Include limit reached; this report is incomplete.")
            break
        try:
            source = read_file(name)
            model = parse_interview_yaml(source)
        except (OSError, ValueError) as exc:
            warnings.append(f"Could not read {name}: {type(exc).__name__}.")
            continue
        files[name] = source
        revision = source_revision(source)
        for block in model["blocks"]:
            block = dict(
                block,
                sourceFile=name,
                sourceLabel=name,
                sourceRevision=revision,
            )
            block["scan_id"] = f"{name}#{block['index']}"
            data = block.get("data") or {}
            if block["type"] == "raw" and not data:
                warnings.append(
                    f"Could not analyze {name}, line {block['line_start']}."
                )
            for target in _strings(data.get("include")):
                if ":" not in target and ":" in name:
                    target = name.split(":")[0] + ":" + target
                pending.append(target)
            blocks.append(block)

    definitions: Dict[str, List[str]] = {}
    index = _DefinitionIndex()
    reads_by_block: Dict[str, Set[str]] = {}
    receivers_by_block: Dict[str, Set[str]] = {}
    roots: Set[str] = set()
    for block in blocks:
        data = block.get("data") or {}
        names: Set[str] = set()
        reads: Set[str] = set()
        receivers: Set[str] = set()
        for key in DEFINITIONS:
            names.update(_strings(data.get(key)))
        for field in (
            data.get("fields", []) if isinstance(data.get("fields"), list) else []
        ):
            if not isinstance(field, dict):
                continue
            names.update(_strings(field.get("field")))
            for label, value in field.items():
                if label not in FIELD_OPTIONS and isinstance(value, str):
                    names.add(value)
        for obj in (
            data.get("objects", []) if isinstance(data.get("objects"), list) else []
        ):
            if isinstance(obj, dict):
                names.update(obj)
        if isinstance(data.get("code"), str):
            r, w = _names(data["code"])
            reads.update(r)
            names.update(w)
        # A review item's value names the variable its Edit button asks again.
        for item in (
            data.get("review", []) if isinstance(data.get("review"), list) else []
        ):
            if isinstance(item, dict):
                for label, value in item.items():
                    if label not in FIELD_OPTIONS | {"button"}:
                        for target in _strings(value):
                            reads.update(_names(target)[0])

        # Traverse all scalar expressions and Mako substitutions without treating
        # user prose or metadata as variable names.
        def visit(value: Any, key: str = "") -> None:
            if isinstance(value, dict):
                for k, v in value.items():
                    visit(k)
                    visit(v, str(k))
            elif isinstance(value, list):
                for item in value:
                    visit(item, key)
            elif isinstance(value, str):
                if key in {
                    "code",
                    "show if",
                    "hide if",
                    "if",
                    "need",
                    "depends on",
                    "default code",
                    "choices code",
                    "validation code",
                    "rows",
                }:
                    reads.update(_names(value)[0])
                    receivers.update(_receivers(value))
                mako_reads, mako_receivers = _mako_uses(value)
                reads.update(mako_reads)
                receivers.update(mako_receivers)

        visit(data)
        bid = block["scan_id"]
        reads_by_block[bid] = {_key(n) for n in reads}
        receivers_by_block[bid] = {_key(n) for n in receivers}
        block["defines"] = sorted(names)
        block["references"] = sorted(reads)
        # Actions can run an event block at any time, as can a mandatory block.
        if data.get("mandatory") or data.get("initial") or data.get("event"):
            roots.add(bid)
        generic = bool(data.get("generic object"))
        for name in names:
            definitions.setdefault(_key(name), []).append(bid)
            index.add(_key(name), generic)

    def used_names(bid: str) -> Set[str]:
        found: Set[str] = set()
        for name in reads_by_block[bid]:
            found.update(index.read(name))
        for name in receivers_by_block[bid]:
            found.update(index.receiver(name))
        return found

    uses_by_block = {bid: used_names(bid) for bid in reads_by_block}
    reachable = set(roots)
    pending_ids = list(roots)
    while pending_ids:
        bid = pending_ids.pop()
        for name in uses_by_block[bid]:
            for target in definitions[name]:
                if target not in reachable:
                    reachable.add(target)
                    pending_ids.append(target)
    variables = []
    for name, defined in sorted(definitions.items()):
        used = [
            bid
            for bid, uses in uses_by_block.items()
            if name in uses and bid not in defined
        ]
        variables.append(
            {
                "name": name,
                "definitions": defined,
                "references": used,
                "possibly_unused": not used and not any(b in roots for b in defined),
            }
        )
    for block in blocks:
        block["possibly_unreachable"] = (
            bool(block["defines"] or "question" in (block.get("data") or {}))
            and block["scan_id"] not in reachable
        )
    named_orders: Dict[str, List[Dict[str, Any]]] = {}
    local = [b for b in blocks if ":" not in b["sourceFile"]]
    has_main = any(_is_main_order(b) for b in local)
    orders: List[Dict[str, Any]] = []
    for block in blocks:
        data = block.get("data") or {}
        code = data.get("code")
        if isinstance(code, str):
            steps = parse_order_code(code)
            match = re.search(r"(?:^|\n)\s*(\w+)\s*=\s*True\s*(?:#.*)?\s*$", code)
            if match:
                named_orders.setdefault(match[1], steps)
            if ":" not in block["sourceFile"] and (
                _is_main_order(block) if has_main else data.get("mandatory")
            ):
                orders.extend(steps)
        elif (
            data.get("mandatory")
            and "question" in data
            and ":" not in block["sourceFile"]
        ):
            orders.append(
                {
                    "kind": "screen",
                    "source_block": block["scan_id"],
                    "invoke": block.get("variable") or "",
                    "summary": block["title"],
                }
            )
    if not orders:
        for block in local:
            data = block.get("data") or {}
            if isinstance(data.get("code"), str) and re.match(
                r"^interview[ _]order", str(data.get("id", "")), re.I
            ):
                orders.extend(parse_order_code(data["code"]))
    literals = _report_literals(blocks)
    if blocks:
        blocks[0]["report_literals"] = literals
    for block in blocks:
        question = (block.get("data") or {}).get("question")
        if isinstance(question, str):
            title = re.sub(
                r"\$\{\s*(\w+)\s*\}", lambda m: literals.get(m[1], m[0]), question
            )
            if title != question:
                block["report_title"] = title.strip().split("\n")[0]
    screen_order = _screen_order(expand_report_steps(orders, named_orders), blocks)
    return {
        "symbols": _symbols(blocks, package),
        "filename": filename,
        "blocks": blocks,
        "variables": variables,
        "order_steps": orders,
        "screen_order": screen_order,
        "named_order_steps": named_orders,
        "warnings": warnings,
        "files": list(files),
        "revisions": {n: source_revision(s) for n, s in files.items()},
        "limitation": "Static hints only: dynamic names, imported Python, templates and runtime conditions may add uses or change reachability.",
    }
