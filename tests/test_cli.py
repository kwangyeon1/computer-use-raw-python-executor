from __future__ import annotations

import argparse
from pathlib import Path

from computer_use_raw_python_executor.cli import (
    _capture_screen,
    _current_observation,
    _filter_ocr_lines_to_region,
    _normalize_screenshot_region,
    _run_windows_ocr,
    _screen_browser_region_fallback,
    _summarize_ocr_lines,
)


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


def test_filter_ocr_lines_to_region_keeps_only_browser_window_lines() -> None:
    lines = [
        {"text": "다운로드", "left": 1100, "top": 140, "width": 90, "height": 28},
        {"text": "run-session --task", "left": 50, "top": 200, "width": 220, "height": 24},
    ]
    region = {"left": 400, "top": 0, "right": 1360, "bottom": 760}
    filtered = _filter_ocr_lines_to_region(lines, region)
    assert [item["text"] for item in filtered] == ["다운로드"]


def test_screen_browser_region_fallback_prefers_right_side_of_screen(monkeypatch) -> None:
    monkeypatch.setattr("computer_use_raw_python_executor.cli._screen_metrics", lambda: (1600, 900))
    region = _screen_browser_region_fallback()
    assert region["left"] >= 400
    assert region["right"] <= 1590
    assert region["bottom"] >= 860


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
    assert str(calls[0]["env"]["COMPUTER_USE_OCR_IMAGE_PATH"]).replace("\\", "/") == "C:/Temp/example.png"
    assert "C:/Temp/example.png" not in calls[0]["args"]


def test_current_observation_does_not_auto_generate_windows_ocr_summary(monkeypatch) -> None:
    screenshot_payload = {
        "screenshot_path": "C:/Temp/example.png",
        "screenshot_base64": "ZmFrZQ==",
        "screenshot_media_type": "image/png",
    }
    monkeypatch.setattr(
        "computer_use_raw_python_executor.cli._capture_screen",
        lambda: screenshot_payload,
    )
    monkeypatch.setattr(
        "computer_use_raw_python_executor.cli._observation_text_from_screenshot_payload",
        lambda payload: "OCR visible text: Download",
    )

    result = _current_observation(
        argparse.Namespace(
            observation_text=None,
            observation_file=None,
            screenshot_path=None,
        )
    )

    assert result["observation_text"] is None
    assert result["screenshot_base64"] == "ZmFrZQ=="


def test_capture_screen_accepts_optional_region(monkeypatch) -> None:
    calls: list[object] = []

    class FakeImage:
        def save(self, buffer, format):  # type: ignore[no-untyped-def]
            buffer.write(b"fake-png")

    def fake_grab(*, bbox=None):
        calls.append(bbox)
        return FakeImage()

    monkeypatch.setattr("PIL.ImageGrab.grab", fake_grab)

    result = _capture_screen({"left": 10, "top": 20, "right": 110, "bottom": 220})

    assert calls == [(10, 20, 110, 220)]
    assert result["screenshot_region"] == {"left": 10, "top": 20, "right": 110, "bottom": 220}
    assert result["screenshot_base64"]


def test_normalize_screenshot_region_supports_installer_window_mode(monkeypatch) -> None:
    monkeypatch.setattr(
        "computer_use_raw_python_executor.cli._installer_window_region",
        lambda: {"left": 5, "top": 6, "right": 105, "bottom": 206},
    )

    assert _normalize_screenshot_region({"mode": "installer_window"}) == {
        "left": 5,
        "top": 6,
        "right": 105,
        "bottom": 206,
    }


def test_normalize_screenshot_region_prefers_expected_pid_window(monkeypatch) -> None:
    calls: list[int | None] = []

    def fake_pid_region(pid):
        calls.append(pid)
        return {"left": 20, "top": 30, "right": 420, "bottom": 330}

    monkeypatch.setattr(
        "computer_use_raw_python_executor.cli._window_region_for_process_tree",
        fake_pid_region,
    )
    monkeypatch.setattr(
        "computer_use_raw_python_executor.cli._installer_window_region",
        lambda: {"left": 5, "top": 6, "right": 105, "bottom": 206},
    )

    assert _normalize_screenshot_region({"mode": "installer_window", "expected_pid": "1234"}) == {
        "left": 20,
        "top": 30,
        "right": 420,
        "bottom": 330,
    }
    assert calls == [1234]


def test_normalize_screenshot_region_falls_back_when_expected_pid_window_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "computer_use_raw_python_executor.cli._window_region_for_process_tree",
        lambda _pid: None,
    )
    monkeypatch.setattr(
        "computer_use_raw_python_executor.cli._installer_window_region",
        lambda: {"left": 5, "top": 6, "right": 105, "bottom": 206},
    )

    assert _normalize_screenshot_region({"mode": "installer_window", "expected_pid": 1234}) == {
        "left": 5,
        "top": 6,
        "right": 105,
        "bottom": 206,
    }
