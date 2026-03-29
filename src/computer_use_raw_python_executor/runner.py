from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import subprocess
import sys
import time

from .models import ExecutionPayload


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_run_dir(run_dir: str | Path) -> Path:
    path = Path(run_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def append_event(run_dir: str | Path, event_type: str, payload: dict) -> None:
    path = ensure_run_dir(run_dir) / "events.jsonl"
    line = {"timestamp": _utc_now(), "event_type": event_type, "payload": payload}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line, ensure_ascii=False) + "\n")


def execute_payload(
    payload: ExecutionPayload,
    run_dir: str | Path,
    *,
    python_bin: str | None = None,
    timeout_s: int = 180,
) -> dict:
    run_path = ensure_run_dir(run_dir)
    script_path = run_path / "generated.py"
    stdout_path = run_path / "stdout.log"
    stderr_path = run_path / "stderr.log"
    metadata_path = run_path / "execution.json"
    payload_path = run_path / "payload.json"
    interpreter = python_bin or sys.executable

    script_path.write_text(payload.code, encoding="utf-8")
    payload_path.write_text(json.dumps(payload.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    append_event(run_path, "execution_started", {"step_id": payload.step_id, "python_bin": interpreter})

    started = time.monotonic()
    timed_out = False
    try:
        with stdout_path.open("w", encoding="utf-8") as stdout_handle, stderr_path.open(
            "w", encoding="utf-8"
        ) as stderr_handle:
            completed = subprocess.run(
                [interpreter, str(script_path)],
                cwd=str(run_path),
                stdout=stdout_handle,
                stderr=stderr_handle,
                text=True,
                timeout=timeout_s,
                check=False,
            )
        return_code = completed.returncode
    except subprocess.TimeoutExpired:
        return_code = -1
        timed_out = True
        with stderr_path.open("a", encoding="utf-8") as stderr_handle:
            stderr_handle.write(f"\nTimed out after {timeout_s}s\n")
    duration_s = round(time.monotonic() - started, 3)

    record = {
        "step_id": payload.step_id,
        "run_dir": str(run_path),
        "generated_script": str(script_path),
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "metadata_path": str(metadata_path),
        "return_code": return_code,
        "timed_out": timed_out,
        "duration_s": duration_s,
        "payload_metadata": payload.metadata,
    }
    metadata_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    append_event(run_path, "execution_finished", record)
    return record
