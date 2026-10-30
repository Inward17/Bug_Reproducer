"""AST-based static analysis for generated scripts.

This is lint, not a security boundary — the container is the boundary. Its job is to
stop an LLM from wandering outside the browser-automation API it was asked for.

It uses an allow-list: a deny-list of module names was trivially sidestepped with
``importlib.import_module('o' + 's')``, ``ctypes`` or ``urllib.request``.
"""

import ast
import posixpath

# Everything a Selenium reproduction script legitimately needs.
ALLOWED_IMPORTS = {
    "selenium",
    "time", "datetime", "re", "json", "math", "random", "string",
    "collections", "itertools", "functools", "textwrap", "traceback", "typing",
    "dataclasses", "enum", "decimal", "unicodedata", "html", "base64", "uuid",
}

# Builtins that turn a script into an arbitrary-code loader.
BLOCKED_BUILTINS = {
    "eval", "exec", "compile", "__import__", "getattr", "setattr", "delattr",
    "globals", "locals", "vars", "breakpoint", "input", "help", "memoryview",
    "exit", "quit", "license", "credits",
}

SCREENSHOT_ROOT = "/screenshots/"


class SecurityError(Exception):
    """Raised when a script contains unsafe constructs."""
    pass


def _check_import(node: ast.Import | ast.ImportFrom) -> None:
    names = [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        # `from . import x` has module=None; relative imports have nothing to resolve.
        if node.level:
            raise SecurityError("Relative imports are not allowed")
        names = [node.module or ""]

    for name in names:
        root = name.split(".")[0]
        if root not in ALLOWED_IMPORTS:
            raise SecurityError(
                f"Import {name!r} is not on the allow-list. Allowed: "
                f"{', '.join(sorted(ALLOWED_IMPORTS))}")


def _is_open_call(func: ast.expr) -> bool:
    return ((isinstance(func, ast.Name) and func.id == "open")
            or (isinstance(func, ast.Attribute) and func.attr == "open"))


def _check_open(node: ast.Call) -> None:
    """Allow only open() on a literal path under /screenshots/."""
    if (node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
            and posixpath.normpath(node.args[0].value).startswith(SCREENSHOT_ROOT)):
        return
    raise SecurityError(f"open() outside {SCREENSHOT_ROOT} is blocked")


def check(script: str) -> None:
    """Raise SecurityError if the script contains unsafe constructs."""
    try:
        tree = ast.parse(script)
    except SyntaxError as e:
        raise SecurityError(f"Syntax error: {e}") from e

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            _check_import(node)

        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in BLOCKED_BUILTINS:
                raise SecurityError(f"Blocked builtin: {node.func.id}()")
            if _is_open_call(node.func):
                _check_open(node)

        # Dunder access is the standard route from any object back to the interpreter
        # internals (obj.__class__.__bases__[0].__subclasses__(), f.__globals__, ...).
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("__") and node.attr.endswith("__"):
                raise SecurityError(f"Blocked dunder attribute access: .{node.attr}")

        elif isinstance(node, ast.Name):
            if node.id.startswith("__") and node.id.endswith("__") and node.id != "__name__":
                raise SecurityError(f"Blocked dunder name: {node.id}")
