"""Runs inside the sandbox subprocess (`python -I sandbox_runner.py <workdir>`). Never imported by the app.

Reads <workdir>/code.py and <workdir>/data.json, executes the code with `df` (a DataFrame of the
query result), `pd` and `np` in scope, and prints ONE json line: {ok, stdout, error, table, value}.

This is defence in depth for LLM-written analysis code over a read-only query result, not a hard
security boundary: AST allowlist + restricted builtins + resource limits + stripped environment +
a hard timeout enforced by the parent. Run the backend in a container for stronger isolation.
"""

import ast
import builtins
import io
import json
import math
import re
import resource
import sys
import traceback
from contextlib import redirect_stdout
from pathlib import Path

ALLOWED_IMPORTS = {
    "pandas", "numpy", "math", "statistics", "datetime", "collections", "itertools", "functools",
    "json", "re", "decimal", "fractions", "random", "calendar", "string", "operator", "heapq", "bisect",
}
BLOCKED_NAMES = {
    "open", "exec", "eval", "compile", "__import__", "input", "breakpoint", "globals", "locals", "vars",
    "getattr", "setattr", "delattr", "exit", "quit", "help", "memoryview", "classmethod", "staticmethod",
    "property", "super", "type", "object",
}
BLOCKED_ATTRS = {
    "os", "sys", "subprocess", "io", "builtins", "importlib", "ctypes", "pickle", "shutil", "socket",
    "system", "popen", "environ", "modules", "eval", "query", "pipe", "read_pickle", "load", "loadtxt",
    "genfromtxt", "fromfile", "tofile", "memmap", "save", "savez", "savetxt", "ctypeslib", "testing",
    "to_pickle", "to_csv", "to_parquet", "to_excel", "to_sql", "to_hdf", "to_feather", "to_orc",
    "to_stata", "to_clipboard", "to_xml", "to_latex", "to_html", "to_markdown", "to_gbq",
}
SAFE_BUILTINS = {
    name: getattr(builtins, name)
    for name in (
        "abs all any bin bool bytes callable chr dict divmod enumerate filter float format frozenset hash hex "
        "int isinstance issubclass iter len list map max min next oct ord pow print range repr reversed round "
        "set slice sorted str sum tuple zip complex Exception ValueError TypeError KeyError IndexError "
        "ZeroDivisionError ArithmeticError StopIteration AttributeError RuntimeError NameError "
        "True False None"
    ).split()
}
MAX_TABLE_ROWS = 200
MAX_STDOUT = 8000


def _check(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] not in ALLOWED_IMPORTS:
                    raise ValueError(f"import of '{alias.name}' is not allowed")
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] not in ALLOWED_IMPORTS or node.level:
                raise ValueError(f"import from '{node.module}' is not allowed")
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("_") or node.attr in BLOCKED_ATTRS or node.attr.startswith("read_"):
                raise ValueError(f"attribute '{node.attr}' is not allowed")
        elif isinstance(node, ast.Name):
            if node.id in BLOCKED_NAMES or (node.id.startswith("__") and node.id != "__name__"):
                raise ValueError(f"name '{node.id}' is not allowed")
        elif isinstance(node, (ast.ClassDef, ast.AsyncFunctionDef, ast.Await, ast.Global, ast.Nonlocal)):
            raise ValueError(f"{type(node).__name__} is not allowed")


def _limits(cpu_seconds: int, memory_mb: int) -> None:
    for which, value in (
        (resource.RLIMIT_CPU, cpu_seconds),
        (resource.RLIMIT_FSIZE, 1_000_000),
        (resource.RLIMIT_CORE, 0),
    ):
        try:
            resource.setrlimit(which, (value, value))
        except (ValueError, OSError):
            pass
    if sys.platform.startswith("linux"):  # macOS ignores RLIMIT_AS
        try:
            limit = memory_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
        except (ValueError, OSError):
            pass


def _jsonable(value):
    import numpy as np
    import pandas as pd

    if value is None or value is pd.NaT:
        return None
    if isinstance(value, (bool, str)):
        return value
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        value = float(value)
        return None if math.isnan(value) or math.isinf(value) else value
    if isinstance(value, int):
        return value
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return str(value)


def _frame(columns, rows):
    import pandas as pd

    df = pd.DataFrame(rows, columns=columns)
    iso = re.compile(r"^\d{4}-\d{2}-\d{2}")
    for col in df.columns:
        series = df[col]
        if series.dtype != object and str(series.dtype) not in ("str", "string"):
            continue
        sample = next((v for v in series if v is not None), None)
        if isinstance(sample, str) and iso.match(sample):
            try:
                df[col] = pd.to_datetime(series)
                continue
            except (ValueError, TypeError):
                pass
        try:
            df[col] = pd.to_numeric(series)
        except (ValueError, TypeError):
            pass
    return df


def _table(result):
    import pandas as pd

    if isinstance(result, pd.Series):
        result = result.to_frame()
    if isinstance(result, pd.DataFrame):
        total = len(result)
        frame = result.head(MAX_TABLE_ROWS).reset_index()
        if list(result.index.names) == [None] and isinstance(result.index, pd.RangeIndex):
            frame = frame.drop(columns="index")
        return {
            "columns": [str(c) for c in frame.columns],
            "rows": [[_jsonable(v) for v in row] for row in frame.itertuples(index=False, name=None)],
            "rowCount": total,
            "truncated": total > MAX_TABLE_ROWS,
        }
    return None


def main() -> None:
    workdir = Path(sys.argv[1])
    cpu_seconds, memory_mb = int(sys.argv[2]), int(sys.argv[3])
    _limits(cpu_seconds, memory_mb)

    out: dict = {"ok": False, "stdout": "", "error": None, "table": None, "value": None}
    buffer = io.StringIO()
    try:
        import numpy as np
        import pandas as pd

        code = (workdir / "code.py").read_text()
        data = json.loads((workdir / "data.json").read_text())
        tree = ast.parse(code, mode="exec")
        _check(tree)

        def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: A002
            if level or name.split(".")[0] not in ALLOWED_IMPORTS:
                raise ImportError(f"import of '{name}' is not allowed")
            return builtins.__import__(name, globals, locals, fromlist, level)

        env = {
            "__builtins__": {**SAFE_BUILTINS, "__import__": guarded_import},
            "__name__": "__sandbox__",
            "pd": pd,
            "np": np,
            "df": _frame(data["columns"], data["rows"]),
        }
        with redirect_stdout(buffer):
            exec(compile(tree, "<analysis>", "exec"), env)  # noqa: S102
        result = env.get("result")
        out["table"] = _table(result)
        if out["table"] is None and result is not None:
            out["value"] = _jsonable(result)
        out["ok"] = True
    except BaseException as exc:  # noqa: BLE001 — everything must come back as JSON
        tb = traceback.extract_tb(exc.__traceback__)
        line = next((f.lineno for f in reversed(tb) if f.filename == "<analysis>"), None)
        out["error"] = f"{type(exc).__name__}: {exc}" + (f" (line {line})" if line else "")
    out["stdout"] = buffer.getvalue()[:MAX_STDOUT]
    sys.__stdout__.write("\n" + json.dumps(out, default=str) + "\n")


if __name__ == "__main__":
    main()
