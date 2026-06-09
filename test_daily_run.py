#!/usr/bin/env python3
"""Focused tests for daily_run.py."""

from __future__ import annotations

import io
import os
import sys
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

import daily_run


def reset_ytdlp_cache() -> None:
    daily_run._YTDLP_BASE = None


def completed(stdout: str = "", returncode: int = 0) -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")


def test_detect_ytdlp_prefers_env_command():
    reset_ytdlp_cache()

    def fake_run(cmd, **kwargs):
        assert cmd == ["custom-ytdlp", "--version"]
        return completed("2026.01.01\n")

    with patch.dict(os.environ, {"YTDLP_CMD": "custom-ytdlp"}, clear=True):
        with patch("daily_run.shutil.which", return_value="/opt/homebrew/bin/yt-dlp"):
            with patch("daily_run.subprocess.run", side_effect=fake_run):
                detected = daily_run.detect_ytdlp_base()

    assert detected == ["custom-ytdlp", *daily_run.YTDLP_COMMON_ARGS]


def test_detect_ytdlp_uses_path_before_python_module():
    reset_ytdlp_cache()

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return completed("2026.01.01\n")

    with patch.dict(os.environ, {}, clear=True):
        with patch("daily_run.shutil.which", return_value="/opt/homebrew/bin/yt-dlp"):
            with patch("daily_run.subprocess.run", side_effect=fake_run):
                detected = daily_run.detect_ytdlp_base()

    assert calls == [["yt-dlp", "--version"]]
    assert detected == ["yt-dlp", *daily_run.YTDLP_COMMON_ARGS]


def test_detect_ytdlp_falls_back_to_python_module():
    reset_ytdlp_cache()

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        assert cmd == [sys.executable, "-m", "yt_dlp", "--version"]
        return completed("2026.01.01\n")

    with patch.dict(os.environ, {}, clear=True):
        with patch("daily_run.shutil.which", return_value=None):
            with patch("daily_run.subprocess.run", side_effect=fake_run):
                detected = daily_run.detect_ytdlp_base()

    assert calls == [[sys.executable, "-m", "yt_dlp", "--version"]]
    assert detected == [sys.executable, "-m", "yt_dlp", *daily_run.YTDLP_COMMON_ARGS]


def test_dry_run_does_not_upload_pipeline_or_write_history():
    reset_ytdlp_cache()
    argv = ["daily_run.py", "--dry-run", "--long-only"]
    videos = [{"id": "long123", "title": "Long Video", "duration": 900}]

    with patch.object(sys, "argv", argv):
        with patch("daily_run.load_history", return_value=set()):
            with patch("daily_run.get_playlist_videos", return_value=videos):
                with patch("daily_run.run_pipeline", side_effect=AssertionError("run_pipeline should not be called")):
                    with patch("daily_run.upload_to_bili", side_effect=AssertionError("upload_to_bili should not be called")):
                        with patch("daily_run.save_history", side_effect=AssertionError("save_history should not be called")):
                            output = io.StringIO()
                            with redirect_stdout(output):
                                daily_run.main()

    text = output.getvalue()
    assert "计划模式" in text
    assert "[PLAN] 长视频候选: Long Video" in text


def test_no_upload_does_not_upload_pipeline_or_write_history():
    reset_ytdlp_cache()
    argv = ["daily_run.py", "--no-upload", "--short-only"]
    videos = [{"id": "short123", "title": "Short Video", "duration": 60}]

    with patch.object(sys, "argv", argv):
        with patch("daily_run.load_history", return_value=set()):
            with patch("daily_run.get_playlist_videos", return_value=videos):
                with patch("daily_run.run_pipeline", side_effect=AssertionError("run_pipeline should not be called")):
                    with patch("daily_run.upload_to_bili", side_effect=AssertionError("upload_to_bili should not be called")):
                        with patch("daily_run.save_history", side_effect=AssertionError("save_history should not be called")):
                            output = io.StringIO()
                            with redirect_stdout(output):
                                daily_run.main()

    text = output.getvalue()
    assert "计划模式" in text
    assert "[PLAN] 短视频候选: Short Video" in text


def run_all_tests():
    tests = [
        test_detect_ytdlp_prefers_env_command,
        test_detect_ytdlp_uses_path_before_python_module,
        test_detect_ytdlp_falls_back_to_python_module,
        test_dry_run_does_not_upload_pipeline_or_write_history,
        test_no_upload_does_not_upload_pipeline_or_write_history,
    ]
    for test in tests:
        test()
        print(f"✅ {test.__name__}")
    print(f"结果: {len(tests)} passed, 0 failed, {len(tests)} total")


if __name__ == "__main__":
    run_all_tests()
