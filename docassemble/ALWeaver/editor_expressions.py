# do not pre-load
"""Parse a deliberately bounded Python subset without evaluating interview code.

The tree is ephemeral UI data, never interview storage. Unknown syntax stays in
the source editor. Code trees carry ranges so comments survive guided edits.
"""

import ast
import io
import re
import tokenize

OPERATORS = {
    ast.And: "and",
    ast.Or: "or",
    ast.Not: "not",
    ast.USub: "-",
    ast.UAdd: "+",
    ast.Eq: "==",
    ast.NotEq: "!=",
    ast.Lt: "<",
    ast.LtE: "<=",
    ast.Gt: ">",
    ast.GtE: ">=",
    ast.In: "in",
    ast.NotIn: "not in",
    ast.Add: "+",
    ast.Sub: "-",
    ast.Mult: "*",
    ast.Div: "/",
}


def _reference(node):
    if isinstance(node, ast.Name):
        return True
    if isinstance(node, ast.Attribute):
        return _reference(node.value)
    if isinstance(node, ast.Subscript):
        return _reference(node.value) and (
            isinstance(node.slice, ast.Name)
            or isinstance(node.slice, ast.Constant)
            and type(node.slice.value) in (str, int)
        )
    return False


def _offset(source, line, col):
    lines = re.split(r"(?<=\n)|(?<=\r)(?!\n)", source)
    return len("".join(lines[: line - 1])) + len(
        lines[line - 1].encode("utf-8")[:col].decode("utf-8")
    )


def _tree(node, source):
    tree = _tree_value(node, source)
    tree["start"] = _offset(source, node.lineno, node.col_offset)
    tree["end"] = _offset(source, node.end_lineno, node.end_col_offset)
    return tree


def _tree_value(node, source):
    if _reference(node):
        return {"kind": "variable", "value": ast.get_source_segment(source, node)}
    if isinstance(node, ast.Constant):
        kind = {
            str: "text",
            int: "number",
            float: "number",
            bool: "boolean",
            type(None): "none",
        }.get(type(node.value))
        if kind:
            return {
                "kind": kind,
                "value": (
                    node.value
                    if kind == "text"
                    else ast.get_source_segment(source, node)
                ),
            }
    if (
        isinstance(node, (ast.BoolOp, ast.BinOp, ast.UnaryOp))
        and type(node.op) in OPERATORS
    ):
        children = (
            node.values
            if isinstance(node, ast.BoolOp)
            else (
                [node.left, node.right]
                if isinstance(node, ast.BinOp)
                else [node.operand]
            )
        )
        return {
            "kind": "operator",
            "op": OPERATORS[type(node.op)],
            "args": [_tree(n, source) for n in children],
        }
    if isinstance(node, ast.Compare) and all(type(op) in OPERATORS for op in node.ops):
        return {
            "kind": "comparison",
            "ops": [OPERATORS[type(op)] for op in node.ops],
            "args": [_tree(n, source) for n in [node.left, *node.comparators]],
        }
    if isinstance(node, (ast.List, ast.Tuple)):
        return {
            "kind": "list" if isinstance(node, ast.List) else "tuple",
            "args": [_tree(n, source) for n in node.elts],
        }
    if (
        isinstance(node, ast.Call)
        and _reference(node.func)
        and all(keyword.arg is not None for keyword in node.keywords)
    ):
        return {
            "kind": "function",
            "name": ast.get_source_segment(source, node.func),
            "args": [_tree(n, source) for n in node.args]
            + [_tree(keyword.value, source) for keyword in node.keywords],
            "keywords": [None] * len(node.args)
            + [keyword.arg for keyword in node.keywords],
        }
    raise ValueError("This Python syntax needs the source editor.")


def parse_expression(source, context="value"):
    """Return syntax validity, guided support, and exact expression ranges.

    Ranges count Unicode code points (the client uses Array.from), unlike AST
    columns, which count UTF-8 bytes. No source is normalized or executed.
    """
    if not isinstance(source, str) or len(source) > 20000:
        return {
            "supported": False,
            "valid": False,
            "reason": "Use source editing for inputs over 20,000 characters.",
        }
    if context not in ("value", "boolean", "code"):
        return {
            "supported": False,
            "valid": False,
            "reason": "Unknown expression context.",
        }
    try:
        parsed = ast.parse(
            source,
            mode="exec" if context == "code" else "eval",
        )
        # ast.parse alone accepts some invalid calls, e.g. repeated keywords.
        # Compile only checks validity; it does not execute the expression.
        compile(parsed, "<expression>", "exec" if context == "code" else "eval")
    except (SyntaxError, ValueError, RecursionError) as exc:
        return {"supported": False, "valid": False, "reason": str(exc)}
    try:
        if sum(1 for _ in ast.walk(parsed)) > 300:
            raise ValueError("This expression is too large for guided editing.")
        comments = [
            t
            for t in tokenize.generate_tokens(io.StringIO(source).readline)
            if t.type == tokenize.COMMENT
        ]
        if comments and context != "code":
            raise ValueError("Use Python editing to preserve comments.")
        if context != "code":
            return {
                "supported": True,
                "valid": True,
                "tree": _tree(parsed.body, source),
            }
        # str.splitlines also splits Unicode separators inside string literals,
        # but Python's AST only advances its line numbers at CR/LF boundaries.
        lines = re.split(r"(?<=\n)|(?<=\r)(?!\n)", source)

        comment_rows = [
            {
                "text": comment.string,
                # Tokenizer columns are characters; AST columns are bytes.
                "start": len("".join(lines[: comment.start[0] - 1])) + comment.start[1],
                "line": comment.start[0],
            }
            for comment in comments
        ]

        rows = []
        for statement in parsed.body:
            if (
                not isinstance(statement, ast.Assign)
                or len(statement.targets) != 1
                or not _reference(statement.targets[0])
            ):
                raise ValueError(
                    "Guided code editing supports assignments only. Use Python for flow, calls, and other statements."
                )
            expr = statement.value
            rows.append(
                {
                    "target": ast.get_source_segment(source, statement.targets[0]),
                    "tree": _tree(expr, source),
                    "start": _offset(source, expr.lineno, expr.col_offset),
                    "end": _offset(source, expr.end_lineno, expr.end_col_offset),
                    "line": statement.lineno,
                    "end_line": statement.end_lineno,
                }
            )
        if not rows:
            raise ValueError(
                "Enter an assignment in Python to use guided code editing."
            )
        return {
            "supported": True,
            "valid": True,
            "rows": rows,
            "comments": comment_rows,
        }
    except (ValueError, RecursionError, tokenize.TokenError) as exc:
        return {"supported": False, "valid": True, "reason": str(exc)}
