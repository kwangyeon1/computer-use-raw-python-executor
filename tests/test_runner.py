from __future__ import annotations

from pathlib import Path

from computer_use_raw_python_executor.models import ExecutionPayload
from computer_use_raw_python_executor.runner import execute_payload


def test_execute_payload_forces_utf8_child_environment(monkeypatch, tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []

    class Completed:
        returncode = 0

    def fake_run(args, **kwargs):
        calls.append({"args": list(args), "env": dict(kwargs.get("env") or {})})
        return Completed()

    monkeypatch.setattr("computer_use_raw_python_executor.runner.subprocess.run", fake_run)

    payload = ExecutionPayload(step_id="step-000", code="print('ok')", metadata={})
    record = execute_payload(payload, tmp_path)

    assert record["return_code"] == 0
    assert calls
    env = calls[0]["env"]
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["PYTHONUTF8"] == "1"
