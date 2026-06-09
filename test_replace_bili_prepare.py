#!/usr/bin/env python3
"""Tests for local Bilibili replacement preparation."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from replace_bili_prepare import prepare_replacement


def write_history(history_file: Path, records: list[dict]) -> None:
    history_file.parent.mkdir(parents=True, exist_ok=True)
    history_file.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def test_matching_history_record_with_bvid():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        history_file = root / "uploaded" / "history.json"
        output_dir = root / "output"
        output_dir.mkdir(parents=True)
        (output_dir / "G8DJHg428rQ.mp4").write_bytes(b"video")

        write_history(
            history_file,
            [{
                "video_id": "G8DJHg428rQ",
                "bvid": "BV1aF9xBoE84",
                "aid": "123456789",
                "title": "Test Title",
                "description": "Test description",
                "tags": ["tag1", "tag2"],
                "source_url": "https://youtube.com/watch?v=G8DJHg428rQ",
            }],
        )

        output = prepare_replacement("G8DJHg428rQ", history_file=history_file, output_dir=output_dir)
        assert "BV1aF9xBoE84" in output
        assert "123456789" in output
        assert "Test description" in output
        assert "tag1, tag2" in output
        assert "Warnings:" not in output


def test_matching_history_record_without_bvid_or_aid():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        history_file = root / "uploaded" / "history.json"
        output_dir = root / "output"
        output_dir.mkdir(parents=True)
        (output_dir / "demo123.mp4").write_bytes(b"video")

        write_history(
            history_file,
            [{
                "video_id": "demo123",
                "title": "No bvid title",
            }],
        )

        output = prepare_replacement("demo123", history_file=history_file, output_dir=output_dir)
        assert "Bilibili bvid: (not available)" in output
        assert "Bilibili aid: (not available)" in output
        assert "脚本无法自动识别对应的 Bilibili 稿件" in output


def test_missing_output_video():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        history_file = root / "uploaded" / "history.json"
        output_dir = root / "output"
        output_dir.mkdir(parents=True)

        write_history(
            history_file,
            [{
                "video_id": "demo456",
                "bvid": "BV_missing_output",
                "title": "Needs rebuild",
            }],
        )

        try:
            prepare_replacement("demo456", history_file=history_file, output_dir=output_dir)
        except FileNotFoundError as exc:
            assert "找不到本地成品视频" in str(exc)
            assert "请先重跑 pipeline" in str(exc)
            return
        raise AssertionError("missing output video should raise FileNotFoundError")


def test_missing_history_record():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        history_file = root / "uploaded" / "history.json"
        output_dir = root / "output"
        output_dir.mkdir(parents=True)
        write_history(history_file, [])

        try:
            prepare_replacement("missing-id", history_file=history_file, output_dir=output_dir)
        except LookupError as exc:
            assert "找不到 video_id=missing-id 的上传记录" in str(exc)
            return
        raise AssertionError("missing history record should raise LookupError")


def run_all_tests():
    tests = [
        test_matching_history_record_with_bvid,
        test_matching_history_record_without_bvid_or_aid,
        test_missing_output_video,
        test_missing_history_record,
    ]
    for test in tests:
        test()
        print(f"✅ {test.__name__}")
    print(f"结果: {len(tests)} passed, 0 failed, {len(tests)} total")


if __name__ == "__main__":
    run_all_tests()