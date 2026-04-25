from __future__ import annotations

from pathlib import Path
import subprocess


def main() -> int:
    root = Path(__file__).resolve().parent
    python_bin = root / ".venv" / "Scripts" / "python.exe"
    artifact_root = root / "data" / "runs"
    stdout_path = root / "executor.stdout.log"
    stderr_path = root / "executor.stderr.log"

    with stdout_path.open("w", encoding="utf-8", errors="replace") as stdout_handle, stderr_path.open(
        "w", encoding="utf-8", errors="replace"
    ) as stderr_handle:
        process = subprocess.Popen(
            [
                str(python_bin),
                "-m",
                "computer_use_raw_python_executor.cli",
                "--transport",
                "http",
                "--host",
                "127.0.0.1",
                "--port",
                "8790",
                "--artifact-root",
                str(artifact_root),
            ],
            cwd=str(root),
            stdout=stdout_handle,
            stderr=stderr_handle,
        )
    print(process.pid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
