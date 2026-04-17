from __future__ import annotations

from pathlib import Path

from computer_use_raw_python_executor.cli import _run_windows_ocr, _summarize_ocr_lines


def test_summarize_ocr_lines_prefers_download_install_keywords() -> None:
    lines = [
        {"text": "KakaoTalk PC"},
        {"text": "다운로드"},
        {"text": "Windows"},
        {"text": "Open chat"},
    ]
    summary = _summarize_ocr_lines(lines)
    assert summary is not None
    assert "다운로드" in summary
    assert "Windows" in summary
    assert summary.startswith("OCR visible text with download/install cues:")


def test_summarize_ocr_lines_falls_back_to_general_visible_text() -> None:
    lines = [
        {"text": "Welcome"},
        {"text": "Official page"},
        {"text": "Sign in"},
    ]
    summary = _summarize_ocr_lines(lines)
    assert summary is not None
    assert summary.startswith("OCR visible text:")
    assert "Welcome" in summary


def test_summarize_ocr_lines_ignores_terminal_like_download_text() -> None:
    lines = [
        {"text": "./.venv/bin/training-generator --config config/generator.qwen35.json"},
        {"text": '--execution-style gui_first --task "카카오톡 pc버전 프로그램을 설치해줘"'},
        {"text": "responses/step-000.response.json"},
    ]
    assert _summarize_ocr_lines(lines) is None


def test_summarize_ocr_lines_prefers_short_clickable_controls_over_terminal_noise() -> None:
    lines = [
        {"text": "./.venv/bin/training-generator --config config/generator.qwen35.json"},
        {"text": "다운로드"},
        {"text": "Windows"},
        {"text": "응용 프로그램 설치"},
    ]
    summary = _summarize_ocr_lines(lines)
    assert summary is not None
    assert "다운로드" in summary
    assert ".venv" not in summary


def test_run_windows_ocr_passes_image_path_via_environment(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class Completed:
        returncode = 0
        stdout = '{"lines":[{"text":"Download","left":10,"top":20,"width":30,"height":15}]}'

    def fake_run(args, **kwargs):
        calls.append({"args": list(args), "env": dict(kwargs.get("env") or {})})
        return Completed()

    monkeypatch.setattr("computer_use_raw_python_executor.cli.os.name", "nt")
    monkeypatch.setattr("computer_use_raw_python_executor.cli.subprocess.run", fake_run)

    result = _run_windows_ocr(Path("C:/Temp/example.png"))

    assert result == [{"text": "Download", "left": 10, "top": 20, "width": 30, "height": 15}]
    assert calls
    assert calls[0]["env"]["COMPUTER_USE_OCR_IMAGE_PATH"] == "C:/Temp/example.png"
    assert "C:/Temp/example.png" not in calls[0]["args"]
