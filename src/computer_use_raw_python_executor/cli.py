from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from typing import Any
import argparse
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import time

from .models import ExecutionPayload
from .runner import execute_payload


def _read_text(path: str | None) -> str | None:
    if not path:
        return None
    file_path = Path(path)
    if not file_path.exists():
        return None
    return file_path.read_text(encoding="utf-8", errors="replace")


def _read_tail(path: str | None, limit_chars: int = 4000) -> str:
    text = _read_text(path)
    if not text:
        return ""
    return text[-limit_chars:]


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


_OCR_SUMMARY_KEYWORDS = (
    "download",
    "다운로드",
    "install",
    "installer",
    "setup",
    "설치",
    "다음",
    "동의",
    "확인",
    "finish",
    "next",
    "save",
    "open",
    "exe",
    "windows",
    "pc",
)


_WINDOWS_OCR_SCRIPT = r"""
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Runtime.WindowsRuntime

function Await([object] $Operation, [type] $ResultType) {
    $asTaskMethod = [System.WindowsRuntimeSystemExtensions].GetMethods() |
        Where-Object { $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 } |
        Select-Object -First 1
    if ($null -eq $asTaskMethod) {
        throw "Could not locate System.WindowsRuntimeSystemExtensions.AsTask"
    }
    $asTask = $asTaskMethod.MakeGenericMethod($ResultType)
    $netTask = $asTask.Invoke($null, @($Operation))
    $null = $netTask.Wait(-1)
    return $netTask.Result
}

$filePath = $env:COMPUTER_USE_OCR_IMAGE_PATH
if ([string]::IsNullOrWhiteSpace($filePath)) {
    throw "COMPUTER_USE_OCR_IMAGE_PATH is empty"
}
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Storage.FileAccessMode, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.IRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Media.Ocr, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrResult, Windows.Media.Ocr, ContentType = WindowsRuntime]

$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($filePath)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($null -eq $engine) {
    throw "Windows OCR engine unavailable"
}
$result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])

$lines = @()
foreach ($line in $result.Lines) {
    $left = 2147483647
    $top = 2147483647
    $right = -1
    $bottom = -1
    foreach ($word in $line.Words) {
        $rect = $word.BoundingRect
        if ($rect.X -lt $left) { $left = [int]$rect.X }
        if ($rect.Y -lt $top) { $top = [int]$rect.Y }
        if (($rect.X + $rect.Width) -gt $right) { $right = [int]($rect.X + $rect.Width) }
        if (($rect.Y + $rect.Height) -gt $bottom) { $bottom = [int]($rect.Y + $rect.Height) }
    }
    if ($right -lt $left -or $bottom -lt $top) {
        $left = 0
        $top = 0
        $right = 0
        $bottom = 0
    }
    $lines += @{
        text = [string]$line.Text
        left = [int]$left
        top = [int]$top
        width = [int]([Math]::Max(0, $right - $left))
        height = [int]([Math]::Max(0, $bottom - $top))
    }
}

@{
    text = [string]$result.Text
    lines = $lines
} | ConvertTo-Json -Depth 6 -Compress
""".strip()


def _normalize_ocr_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())


def _looks_like_terminal_ocr_line(text: str) -> bool:
    normalized = _normalize_ocr_text(text)
    if not normalized:
        return False
    lowered = normalized.lower()
    terminal_markers = (
        ".venv",
        "python -m",
        "python3",
        "pytest",
        "compileall",
        "powershell",
        "cmd /c",
        "curl ",
        "request.json",
        "response.json",
        "loop-summary",
        "run-session",
        "return-executable-python-only-for-this-chunk",
        "payloads/",
        "responses/",
        "scripts/vibe.py",
        "computer-use-raw-python",
    )
    if any(marker in lowered for marker in terminal_markers):
        return True
    if re.search(r"--[a-z0-9][a-z0-9_-]*", lowered):
        return True
    if re.search(r"\bstep-\d{3}\b", lowered):
        return True
    if re.search(r"\b\d{8}-\d{6}\b", lowered):
        return True
    if re.search(r"[a-z]:\\", lowered):
        return True
    if normalized.count("/") + normalized.count("\\") >= 2:
        return True
    if any(ext in lowered for ext in (".json", ".py", ".log", ".md", ".txt")):
        return True
    words = re.findall(r"\S+", normalized)
    return len(normalized) > 72 and len(words) > 7


def _looks_like_clickable_control_text(text: str) -> bool:
    normalized = _normalize_ocr_text(text)
    if not normalized or _looks_like_terminal_ocr_line(normalized):
        return False
    words = re.findall(r"\S+", normalized)
    return len(normalized) <= 40 and len(words) <= 6


def _screen_metrics() -> tuple[int, int]:
    if os.name != "nt":
        return (0, 0)
    import ctypes

    user32 = ctypes.windll.user32
    return max(1, int(user32.GetSystemMetrics(0))), max(1, int(user32.GetSystemMetrics(1)))


def _screen_browser_region_fallback() -> dict[str, int]:
    screen_width, screen_height = _screen_metrics()
    left = int(screen_width * 0.26)
    top = 0
    right = max(left + 400, screen_width - 10)
    bottom = max(400, screen_height - 40)
    return {
        "left": left,
        "top": top,
        "right": right,
        "bottom": bottom,
    }


def _browser_window_region() -> dict[str, int] | None:
    if os.name != "nt":
        return None
    try:
        import pygetwindow as gw
    except Exception:
        return _screen_browser_region_fallback()

    browser_title_tokens = ("chrome", "edge", "firefox", "brave", "opera", "internet explorer")
    terminal_tokens = ("terminal", "powershell", "command prompt", "cmd", "bash", "python", "codex", "explorer")
    active_window = None
    try:
        active_window = gw.getActiveWindow()
    except Exception:
        active_window = None

    screen_width, screen_height = _screen_metrics()

    def _window_score(window: object) -> int:
        title = str(getattr(window, "title", "") or "").strip()
        if not title:
            return -1
        lowered = title.lower()
        width = int(getattr(window, "width", 0) or 0)
        height = int(getattr(window, "height", 0) or 0)
        left = int(getattr(window, "left", 0) or 0)
        top = int(getattr(window, "top", 0) or 0)
        if width < 320 or height < 320:
            return -1
        if left + width < 0 or top + height < 0:
            return -1
        score = 0
        if any(token in lowered for token in browser_title_tokens):
            score += 60
        if any(token in lowered for token in ("download", "다운로드", "official", "공식", "windows", "pc")):
            score += 15
        if any(token in lowered for token in terminal_tokens):
            score -= 140
        if active_window is not None and window is active_window:
            score += 45
        if width >= int(screen_width * 0.45):
            score += 35
        if left >= int(screen_width * 0.18):
            score += 20
        if width < int(screen_width * 0.35) and left <= int(screen_width * 0.12):
            score -= 35
        if height >= int(screen_height * 0.50):
            score += 10
        score += min((width * height) // 50000, 30)
        return score

    candidates: list[tuple[int, object]] = []
    for window in gw.getAllWindows():
        score = _window_score(window)
        if score > 0:
            candidates.append((score, window))
    if not candidates:
        return _screen_browser_region_fallback()
    candidates.sort(key=lambda item: item[0], reverse=True)
    _, window = candidates[0]
    left = int(getattr(window, "left", 0) or 0)
    top = int(getattr(window, "top", 0) or 0)
    width = int(getattr(window, "width", 0) or 0)
    height = int(getattr(window, "height", 0) or 0)
    screen_width, _ = _screen_metrics()
    if width < int(screen_width * 0.45) and left <= int(screen_width * 0.12):
        return _screen_browser_region_fallback()
    return {
        "left": left,
        "top": top,
        "right": left + width,
        "bottom": top + height,
    }


def _filter_ocr_lines_to_region(lines: list[dict[str, Any]], region: dict[str, int] | None) -> list[dict[str, Any]]:
    if not region:
        return list(lines)
    filtered: list[dict[str, Any]] = []
    left_bound = int(region.get("left", 0))
    top_bound = int(region.get("top", 0))
    right_bound = int(region.get("right", 0))
    bottom_bound = int(region.get("bottom", 0))
    for item in lines:
        left = int(item.get("left") or 0)
        top = int(item.get("top") or 0)
        width = max(1, int(item.get("width") or 0))
        height = max(1, int(item.get("height") or 0))
        center_x = int(left + width / 2)
        center_y = int(top + height / 2)
        if left_bound <= center_x <= right_bound and top_bound <= center_y <= bottom_bound:
            filtered.append(item)
    return filtered


def _summarize_ocr_lines(lines: list[dict[str, Any]], *, max_chars: int = 420) -> str | None:
    seen: set[str] = set()
    normalized_lines: list[str] = []
    for item in lines:
        text = _normalize_ocr_text(str(item.get("text") or ""))
        if len(text) < 2:
            continue
        lowered = text.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        normalized_lines.append(text)
    if not normalized_lines:
        return None

    visible_lines = [text for text in normalized_lines if not _looks_like_terminal_ocr_line(text)]
    if not visible_lines:
        return None

    keyword_hits = [
        text
        for text in visible_lines
        if _looks_like_clickable_control_text(text)
        and any(keyword in text.lower() for keyword in _OCR_SUMMARY_KEYWORDS)
    ]
    selected = keyword_hits[:6] if keyword_hits else visible_lines[:6]
    prefix = "OCR visible text with download/install cues: " if keyword_hits else "OCR visible text: "
    summary = prefix + " | ".join(selected)
    if len(summary) <= max_chars:
        return summary
    return summary[: max_chars - 1].rstrip() + "…"


def _powershell_candidates() -> list[str]:
    return ["powershell.exe", "powershell", "pwsh.exe", "pwsh"]


def _run_windows_ocr(image_path: Path) -> list[dict[str, Any]]:
    if os.name != "nt":
        return []
    for executable in _powershell_candidates():
        try:
            env = dict(os.environ)
            env["COMPUTER_USE_OCR_IMAGE_PATH"] = str(image_path)
            completed = subprocess.run(
                [
                    executable,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    _WINDOWS_OCR_SCRIPT,
                ],
                capture_output=True,
                text=True,
                errors="replace",
                check=False,
                env=env,
                timeout=20,
            )
        except FileNotFoundError:
            continue
        except Exception:
            return []
        if completed.returncode != 0:
            continue
        try:
            payload = json.loads(str(completed.stdout or "").strip())
        except json.JSONDecodeError:
            continue
        raw_lines = payload.get("lines")
        if isinstance(raw_lines, list):
            return [dict(item) for item in raw_lines if isinstance(item, dict)]
    return []


def _observation_text_from_screenshot_payload(screenshot_payload: dict[str, Any]) -> str | None:
    screenshot_path = str(screenshot_payload.get("screenshot_path") or "").strip()
    temp_path: Path | None = None
    image_path: Path | None = None
    try:
        if screenshot_path:
            candidate = Path(screenshot_path)
            if candidate.exists():
                image_path = candidate
        if image_path is None:
            screenshot_base64 = str(screenshot_payload.get("screenshot_base64") or "").strip()
            if not screenshot_base64:
                return None
            image_bytes = base64.b64decode(screenshot_base64)
            with tempfile.NamedTemporaryFile(prefix="executor-ocr-", suffix=".png", delete=False) as handle:
                handle.write(image_bytes)
                temp_path = Path(handle.name)
            image_path = temp_path
        if image_path is None:
            return None
        ocr_lines = _run_windows_ocr(image_path)
        browser_region = _browser_window_region()
        browser_lines = _filter_ocr_lines_to_region(ocr_lines, browser_region)
        return _summarize_ocr_lines(browser_lines or ocr_lines)
    except Exception:
        return None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


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
    if not observation_text:
        observation_text = _observation_text_from_screenshot_payload(screenshot_payload)
    return {
        **screenshot_payload,
        "observation_text": observation_text,
        "capture_error": capture_error,
    }


def _safe_segment(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in value)
    cleaned = cleaned.strip("-")
    return cleaned or "session"


def _resolve_executor_run_dir(args: argparse.Namespace, payload: dict[str, Any]) -> str:
    metadata = dict(payload.get("metadata", {}))
    session_id = _safe_segment(str(metadata.get("agent_session_id") or time.strftime("%Y%m%d-%H%M%S")))
    step_id = _safe_segment(str(payload.get("step_id", "unknown-step")))
    artifact_root = Path(args.artifact_root).resolve()
    return str(artifact_root / session_id / step_id)


_MODULE_NOT_FOUND_RE = re.compile(r"ModuleNotFoundError:\s+No module named ['\"]([^'\"]+)['\"]")


def _classify_execution_error(*, return_code: int, timed_out: bool, stderr_tail: str) -> dict[str, Any] | None:
    if timed_out:
        return {"kind": "timeout", "repairable": False}
    if return_code == 0:
        return None
    match = _MODULE_NOT_FOUND_RE.search(stderr_tail or "")
    if match:
        module_name = match.group(1).strip()
        install_name = module_name.split(".", 1)[0]
        return {
            "kind": "missing_python_module",
            "repairable": True,
            "module_name": module_name,
            "install_name": install_name,
        }
    return None


def _handle_rpc(args: argparse.Namespace, payload: dict[str, Any]) -> dict[str, Any]:
    action = str(payload.get("action", "")).strip()
    if action == "observe":
        return {"ok": True, "action": "observe", **_current_observation(args)}
    if action == "execute":
        python_code = str(payload.get("python_code", ""))
        step_id = str(payload.get("step_id", "unknown-step"))
        metadata = dict(payload.get("metadata", {}))
        run_dir = _resolve_executor_run_dir(args, payload)
        record = execute_payload(
            ExecutionPayload(code=python_code, step_id=step_id, metadata=metadata),
            run_dir,
            python_bin=args.python_bin,
            timeout_s=args.exec_timeout_s,
        )
        stdout_tail = _read_tail(record.get("stdout_path"))
        stderr_tail = _read_tail(record.get("stderr_path"))
        error_info = _classify_execution_error(
            return_code=int(record.get("return_code", 0)),
            timed_out=bool(record.get("timed_out", False)),
            stderr_tail=stderr_tail,
        )
        return {
            "ok": True,
            "action": "execute",
            "record": record,
            "stdout_tail": stdout_tail,
            "stderr_tail": stderr_tail,
            "error_info": error_info,
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
    parser.add_argument("--artifact-root", default="data/runs")
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
