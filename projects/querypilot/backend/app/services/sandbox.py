"""Run agent-written pandas code on a query result in a locked-down subprocess.

See sandbox_runner.py for what the child enforces. The parent adds: a stripped environment, an
empty temp working directory, output size caps and a hard wall-clock timeout (the child is killed).
"""

import json
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import settings

RUNNER = Path(__file__).with_name("sandbox_runner.py")
MAX_INPUT_ROWS = 5000
MAX_CODE_CHARS = 6000


@dataclass
class SandboxResult:
    ok: bool
    stdout: str = ""
    error: str | None = None
    table: dict[str, Any] | None = None
    value: Any = None
    duration_ms: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "stdout": self.stdout,
            "error": self.error,
            "table": self.table,
            "value": self.value,
            "durationMs": self.duration_ms,
        }


def run_python(code: str, columns: list[str], rows: list[list[Any]]) -> SandboxResult:
    if not settings.sandbox_enabled:
        return SandboxResult(False, error="The Python sandbox is disabled (SANDBOX_ENABLED=false).")
    if len(code) > MAX_CODE_CHARS:
        return SandboxResult(False, error=f"Code is too long (max {MAX_CODE_CHARS} characters).")

    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="qp-sandbox-") as tmp:
        workdir = Path(tmp)
        (workdir / "code.py").write_text(code)
        (workdir / "data.json").write_text(json.dumps({"columns": columns, "rows": rows[:MAX_INPUT_ROWS]}, default=str))
        timeout = settings.sandbox_timeout_s
        try:
            proc = subprocess.run(  # noqa: S603 — fixed argv, no shell
                [sys.executable, "-I", str(RUNNER), str(workdir), str(timeout + 2), str(settings.sandbox_memory_mb)],
                cwd=workdir,
                env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "OMP_NUM_THREADS": "1", "PYTHONHASHSEED": "0"},
                capture_output=True,
                text=True,
                timeout=timeout,
                stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired:
            return SandboxResult(
                False, error=f"Timed out after {timeout}s. Simplify the analysis.",
                duration_ms=int((time.perf_counter() - started) * 1000),
            )

    duration_ms = int((time.perf_counter() - started) * 1000)
    line = next((ln for ln in reversed(proc.stdout.splitlines()) if ln.startswith("{")), None)
    if line is None:
        detail = (proc.stderr or "no output").strip().splitlines()[-1:]  # last line only
        return SandboxResult(False, error=f"The analysis process failed: {''.join(detail)}", duration_ms=duration_ms)
    data = json.loads(line)
    return SandboxResult(
        ok=bool(data["ok"]),
        stdout=data.get("stdout", ""),
        error=data.get("error"),
        table=data.get("table"),
        value=data.get("value"),
        duration_ms=duration_ms,
    )
