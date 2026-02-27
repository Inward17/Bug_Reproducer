"""AST-based static code analysis for security — blocks dangerous constructs before execution."""

import ast

BLOCKED_IMPORTS = {"os", "subprocess", "socket", "shutil", "sys", "pathlib"}
BLOCKED_BUILTINS = {"eval", "exec", "compile", "__import__"}


class SecurityError(Exception):
    """Raised when a script contains unsafe constructs."""
    pass


def check(script: str) -> None:
    """Raise SecurityError if the script contains unsafe constructs."""
    try:
        tree = ast.parse(script)
    except SyntaxError as e:
        raise SecurityError(f"Syntax error: {e}") from e

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name.split(".")[0] for a in node.names]
            if isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module.split(".")[0])
            for name in names:
                if name in BLOCKED_IMPORTS:
                    raise SecurityError(f"Blocked import: {name}")

        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in BLOCKED_BUILTINS:
                raise SecurityError(f"Blocked builtin: {node.func.id}()")

        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "open":
                if node.args and isinstance(node.args[0], ast.Constant):
                    if "/screenshots/" not in str(node.args[0].value):
                        raise SecurityError("open() outside /screenshots/ is blocked")
