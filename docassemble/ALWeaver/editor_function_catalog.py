"""Read function help from the interview's already-loaded import tree.

This does not import modules, assemble an interview, or call interview functions.
The playground's existing variable discovery has already loaded the interview.
"""

import ast
import builtins
import inspect
import sys


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
    util = modules.get("docassemble.base.util")
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
