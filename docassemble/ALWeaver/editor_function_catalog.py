"""Read function help from the interview's already-loaded import tree.

This does not assemble an interview or call interview functions, and imports no
module except standard library ones whose exports have no readable source.
The playground's existing variable discovery has already loaded the interview.
"""

import ast
import importlib
import builtins
import inspect
from pathlib import Path
import sys

# Docassemble exposes these implicitly, and `docassemble.base.legal` re-exports
# util. Each contributes ~200 names and ~150 KB of JSON, so the catalog offers a
# curated subset instead (see interview_function_catalog).
IMPLICIT_UTIL_MODULES = ("docassemble.base.util", "docassemble.base.legal")


def _module_source(module_name):
    """Find and parse a module's source without importing it."""
    if not all(part.isidentifier() for part in module_name.split(".")):
        return None
    relative = Path(*module_name.split("."))
    candidates = []
    for root in sys.path:
        candidates.extend(
            (
                Path(root) / relative.with_suffix(".py"),
                Path(root) / relative / "__init__.py",
            )
        )
    # Namespace packages may have additional search roots outside sys.path.
    if module_name.startswith("docassemble."):
        namespace = sys.modules.get("docassemble")
        tail = Path(*module_name.split(".")[1:])
        for root in getattr(namespace, "__path__", ()):
            candidates.extend(
                (
                    Path(root) / tail.with_suffix(".py"),
                    Path(root) / tail / "__init__.py",
                )
            )
    for path in candidates:
        try:
            if not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
                continue
            source = path.read_text(encoding="utf-8")
            return source, ast.parse(source), path.name == "__init__.py"
        except (OSError, UnicodeError, SyntaxError):
            continue
    return None


def _literal_exports(tree):
    """A module's literal ``__all__``; [] when dynamic, None when absent."""
    exports = None
    for statement in tree.body:
        if isinstance(statement, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in statement.targets
        ):
            try:
                exports = ast.literal_eval(statement.value)
            except (ValueError, TypeError):
                exports = []  # Dynamic exports cannot be inferred safely.
    return exports


def module_star_names(module_name, _depth=0):
    """Names ``from module import *`` binds, or None if they cannot be read.

    Without ``__all__`` that is every public top-level name, imports included.
    Star re-exports and a re-exported ``__all__`` (``collections.abc`` does both)
    are followed through their source, never by importing.
    """
    found = _module_source(module_name) if _depth < 8 else None
    if found is None:
        # Compiled or aliased standard library modules (math, os.path) have no
        # source to read; importing the standard library runs no author code.
        if module_name.split(".")[0] in sys.stdlib_module_names:
            try:
                module = importlib.import_module(module_name)
            except ImportError:
                return None
            exported = getattr(module, "__all__", None)
            if exported is None:
                exported = [name for name in dir(module) if not name.startswith("_")]
            return {str(name) for name in exported}
        return None
    tree = found[1]

    def absolute(node):
        if not node.level:
            return node.module or ""
        base = module_name.split(".")
        # A package's __init__ resolves "." to itself; a module to its parent.
        base = base[: len(base) - node.level + (1 if found[2] else 0)]
        return ".".join(base + ([node.module] if node.module else []))

    names = set()
    exports = None
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.ImportFrom):
            source = absolute(node)
            for alias in node.names:
                if alias.name == "*":
                    star = module_star_names(source, _depth + 1)
                    if star is None:
                        return None
                    names.update(star)
                elif alias.name == "__all__":
                    exports = module_star_names(source, _depth + 1)
                    if exports is None:
                        return None
                else:
                    names.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in node.targets
        ):
            try:
                exports = set(ast.literal_eval(node.value))
            except (ValueError, TypeError):
                return None  # A dynamic __all__ could export anything.
        else:
            # Conditional definitions and imports (try/except ImportError, if).
            for child in ast.walk(node):
                if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                    names.add(child.id)
                elif isinstance(
                    child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                ):
                    names.add(child.name)
                elif isinstance(child, (ast.Import, ast.ImportFrom)):
                    names.update(
                        (alias.asname or alias.name).split(".")[0]
                        for alias in child.names
                        if alias.name != "*"
                    )
    if exports is not None:
        return {str(name) for name in exports}
    return {name for name in names if not name.startswith("_")}


def _module_source_functions(module_name, qualified, include_methods=False):
    """Read declared modules not loaded in this worker without importing them."""
    found = _module_source(module_name)
    if found is not None:
        source, tree, _ = found
        exports = _literal_exports(tree)
        result = {}
        declarations = local_function_catalog(source)
        if include_methods:
            for node in tree.body:
                if not isinstance(node, ast.ClassDef) or node.name.startswith("_"):
                    continue
                declarations[node.name] = {
                    "name": node.name,
                    "signature": node.name,
                    "doc": ast.get_docstring(node) or "",
                    "kind": "class",
                }
                for method in node.body:
                    if not isinstance(
                        method, (ast.FunctionDef, ast.AsyncFunctionDef)
                    ) or method.name.startswith("_"):
                        continue
                    name = node.name + "." + method.name
                    declarations[name] = {
                        "name": name,
                        "signature": name + "(" + ast.unparse(method.args) + ")",
                        "doc": ast.get_docstring(method) or "",
                        "kind": "method",
                    }
        for name, info in declarations.items():
            if not qualified and exports is not None:
                if name.split(".", 1)[0] not in exports:
                    continue
            elif name.startswith("_"):
                continue
            call_name = module_name + "." + name if qualified else name
            result[call_name] = dict(
                info,
                name=call_name,
                signature=call_name + info["signature"][len(name) :],
                origin=module_name,
            )
        return result
    return {}


def function_help(name, function, origin):
    try:
        signature = inspect.signature(function, eval_str=False)
        parameters = [
            {
                "name": parameter.name,
                "kind": parameter.kind.name,
                "required": parameter.default is inspect.Parameter.empty
                and parameter.kind
                not in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD),
            }
            for parameter in signature.parameters.values()
        ]
        shape = str(signature)
    except Exception:
        # A custom default object's repr may itself fail (e.g. an un-gathered
        # DAObject). Optional help must never break variable discovery.
        parameters, shape = [], "(…)"
    return {
        "name": name,
        "signature": name + shape,
        "parameters": parameters,
        "doc": (inspect.getdoc(function) or "No documentation available.")[:4000],
        "origin": origin,
    }


def interview_function_catalog(interview, modules=None):
    """Honor modules (star imports), imports (qualified names), and __all__.

    Docassemble's questions_list already includes the transitive YAML includes,
    with the originating package on each question for relative imports.
    """
    modules = sys.modules if modules is None else modules
    catalog = {}
    for name in ("len", "str", "int", "float", "round", "min", "max", "sum", "abs"):
        catalog[name] = function_help(name, getattr(builtins, name), "Python")
    imports = []
    # Docassemble implicitly exposes a small set of utility functions. Do not
    # introspect every public helper in base.util: that makes the picker slow
    # and sends a huge, mostly irrelevant catalog to the browser.
    util = modules.get(IMPLICIT_UTIL_MODULES[0])
    if util is not None and not getattr(interview, "consolidated_metadata", {}).get(
        "suppress loading util", False
    ):
        for name in (
            "defined",
            "value",
            "showifdef",
            "currency",
            "today",
            "as_datetime",
        ):
            function = getattr(util, name, None)
            if function is not None and (
                inspect.isfunction(function) or inspect.isbuiltin(function)
            ):
                catalog[name] = function_help(name, function, "docassemble.base.util")
    for question in getattr(interview, "questions_list", []):
        if question.question_type not in ("modules", "imports"):
            continue
        for name in question.module_list:
            if name.startswith("."):
                name = str(question.package) + name
            imports.append((name, question.question_type == "imports"))
    for module_name, qualified in imports:
        module = modules.get(module_name)
        if module is None:
            catalog.update(_module_source_functions(module_name, qualified))
            continue
        # Even narrowed by __all__, a star import of these adds ~200 entries
        # to every response, which is what the curated list above exists to
        # avoid. A qualified `imports:` still gets them, spelled out.
        if not qualified and module_name in IMPLICIT_UTIL_MODULES:
            continue
        members = vars(module)
        exported = members.get("__all__") if not qualified else None
        for name, value in members.items():
            if exported is not None:
                if name not in exported:
                    continue
            elif name.startswith("_"):
                continue
            if not (inspect.isfunction(value) or inspect.isbuiltin(value)):
                continue
            call_name = module_name + "." + name if qualified else name
            catalog[call_name] = function_help(call_name, value, module_name)
    for question in getattr(interview, "questions_list", []):
        if question.question_type == "code":
            catalog.update(local_function_catalog(getattr(question, "sourcecode", "")))
    return catalog


def local_function_catalog(source):
    """Extract signatures/docstrings from author code without executing it."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return {}
    result = {}
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        positional = node.args.posonlyargs + node.args.args
        required_count = len(positional) - len(node.args.defaults)
        parameters = [
            {
                "name": arg.arg,
                "kind": (
                    "POSITIONAL_ONLY"
                    if index < len(node.args.posonlyargs)
                    else "POSITIONAL_OR_KEYWORD"
                ),
                "required": index < required_count,
            }
            for index, arg in enumerate(positional)
        ]
        if node.args.vararg:
            parameters.append(
                {
                    "name": node.args.vararg.arg,
                    "kind": "VAR_POSITIONAL",
                    "required": False,
                }
            )
        parameters.extend(
            {"name": arg.arg, "kind": "KEYWORD_ONLY", "required": default is None}
            for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults)
        )
        if node.args.kwarg:
            parameters.append(
                {"name": node.args.kwarg.arg, "kind": "VAR_KEYWORD", "required": False}
            )
        result[node.name] = {
            "name": node.name,
            "signature": node.name + "(" + ast.unparse(node.args) + ")",
            "parameters": parameters,
            "doc": ast.get_docstring(node) or "No documentation available.",
            "origin": "Interview code",
        }
    return result
