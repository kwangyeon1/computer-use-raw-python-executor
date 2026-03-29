from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from typing import Any
import argparse
import base64
import json
import sys

from .models import ExecutionPayload
from .runner import execute_payload


def _read_text(path: str | None) -> str | None:
    if not path:
        return None
    file_path = Path(path)
    if not file_path.exists():
        return None
    return file_path.read_text(encoding="utf-8", errors="replace")


def _encode_image_bytes(image_bytes: bytes, *, media_type: str) -> dict[str, Any]:
    return {
        "screenshot_base64": base64.b64encode(image_bytes).decode("ascii"),
        "screenshot_media_type": media_type,
    }


def _load_image_file(path: str | None) -> dict[str, Any]:
    if not path:
        return {
            "screenshot_path": None,
            "screenshot_base64": None,
            "screenshot_media_type": None,
        }
    file_path = Path(path)
    if not file_path.exists():
        return {
            "screenshot_path": path,
            "screenshot_base64": None,
            "screenshot_media_type": None,
        }
    suffix = file_path.suffix.lower()
    if suffix == ".png":
        media_type = "image/png"
    elif suffix in {".jpg", ".jpeg"}:
        media_type = "image/jpeg"
    else:
        media_type = "application/octet-stream"
    return {
        "screenshot_path": str(file_path),
        **_encode_image_bytes(file_path.read_bytes(), media_type=media_type),
    }


def _capture_screen() -> dict[str, Any]:
    from PIL import ImageGrab

    image = ImageGrab.grab()
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return {
        "screenshot_path": None,
        **_encode_image_bytes(buffer.getvalue(), media_type="image/png"),
    }


def _current_observation(args: argparse.Namespace) -> dict[str, Any]:
    observation_text = args.observation_text
    if args.observation_file:
        observation_text = _read_text(args.observation_file)
    capture_error = None
    try:
        screenshot_payload = _capture_screen()
    except Exception as exc:  # pragma: no cover - depends on host display
        capture_error = str(exc)
        screenshot_payload = _load_image_file(args.screenshot_path)
    return {
        **screenshot_payload,
        "observation_text": observation_text,
        "capture_error": capture_error,
    }


def _handle_rpc(args: argparse.Namespace, payload: dict[str, Any]) -> dict[str, Any]:
    action = str(payload.get("action", "")).strip()
    if action == "observe":
        return {"ok": True, "action": "observe", **_current_observation(args)}
    if action == "execute":
        python_code = str(payload.get("python_code", ""))
        run_dir = str(payload["run_dir"])
        step_id = str(payload.get("step_id", "unknown-step"))
        metadata = dict(payload.get("metadata", {}))
        record = execute_payload(
            ExecutionPayload(code=python_code, step_id=step_id, metadata=metadata),
            run_dir,
            python_bin=args.python_bin,
            timeout_s=args.exec_timeout_s,
        )
        return {
            "ok": True,
            "action": "execute",
            "record": record,
            **_current_observation(args),
        }
    raise ValueError(f"unsupported action: {action!r}")


def _stdio_loop(args: argparse.Namespace) -> int:
    for line in sys.stdin:
        payload = line.strip()
        if not payload:
            continue
        if payload == "__quit__":
            return 0
        try:
            response = _handle_rpc(args, json.loads(payload))
        except Exception as exc:  # pragma: no cover - runtime path
            response = {"ok": False, "error": str(exc)}
        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    return 0


class _HttpHandler(BaseHTTPRequestHandler):
    service_args: argparse.Namespace

    def do_GET(self) -> None:  # pragma: no cover - networked path
        if self.path != "/health":
            self.send_error(404)
            return
        body = json.dumps({"ok": True}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # pragma: no cover - networked path
        if self.path != "/rpc":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length).decode("utf-8")
        try:
            payload = json.loads(raw_body)
            response = _handle_rpc(self.service_args, payload)
            status = 200
        except Exception as exc:
            response = {"ok": False, "error": str(exc)}
            status = 400
        body = json.dumps(response, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # pragma: no cover - noise reduction
        return


def _http_loop(args: argparse.Namespace) -> int:  # pragma: no cover - networked path
    _HttpHandler.service_args = args
    server = ThreadingHTTPServer((args.host, args.port), _HttpHandler)
    try:
        server.serve_forever()
    finally:
        server.server_close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="computer-use-raw-python-executor")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8790)
    parser.add_argument("--python-bin")
    parser.add_argument("--exec-timeout-s", type=int, default=180)
    parser.add_argument("--screenshot-path", help="fallback image path if automatic capture fails")
    parser.add_argument("--observation-text")
    parser.add_argument("--observation-file")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.transport == "http":
        raise SystemExit(_http_loop(args))
    raise SystemExit(_stdio_loop(args))


if __name__ == "__main__":
    main()
