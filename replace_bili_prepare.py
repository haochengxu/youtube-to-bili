#!/usr/bin/env python3
"""Prepare a local checklist for manual Bilibili video replacement."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).parent
HISTORY_FILE = SCRIPT_DIR / "uploaded" / "history.json"
OUTPUT_DIR = SCRIPT_DIR / "output"


def load_history(history_file: Path = HISTORY_FILE) -> list[dict]:
    if not history_file.exists():
        raise FileNotFoundError(f"找不到历史记录文件: {history_file}")
    return json.loads(history_file.read_text(encoding="utf-8"))


def find_history_record(video_id: str, history: list[dict]) -> dict | None:
    for item in history:
        if item.get("video_id") == video_id:
            return item
    return None


def resolve_output_video(video_id: str, output_dir: Path = OUTPUT_DIR) -> Path:
    return output_dir / f"{video_id}.mp4"


def _optional_value(record: dict, *keys: str) -> str:
    for key in keys:
        value = record.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def build_checklist(video_id: str, record: dict, output_path: Path) -> tuple[list[str], list[str]]:
    bvid = _optional_value(record, "bvid")
    aid = _optional_value(record, "aid")
    description = _optional_value(record, "description", "desc")
    tags = record.get("tags")
    if isinstance(tags, list):
        tags_text = ", ".join(str(tag).strip() for tag in tags if str(tag).strip())
    else:
        tags_text = _optional_value(record, "tags", "tag")
    source_url = _optional_value(record, "youtube_url", "source_url", "source", "url")

    lines = [
        f"Bilibili replacement checklist for {video_id}",
        f"- Local output video path: {output_path}",
        f"- Local output exists: {'yes' if output_path.exists() else 'no'}",
        f"- Title: {_optional_value(record, 'title') or '(missing)'}",
        f"- Description: {description or '(not available)'}",
        f"- Tags: {tags_text or '(not available)'}",
        f"- Original YouTube URL: {source_url or '(not available)'}",
        f"- Bilibili bvid: {bvid or '(not available)'}",
        f"- Bilibili aid: {aid or '(not available)'}",
        "",
        "Manual steps:",
        "1. Confirm the rebuilt local video is correct.",
        "2. Open Bilibili Creator Center and find the existing submission.",
        "3. Use the metadata below to manually edit/replace the submission.",
        "4. Do not run any upload or replacement script automatically.",
    ]

    warnings: list[str] = []
    if not bvid and not aid:
        warnings.append(
            "缺少 bvid / aid，脚本无法自动识别对应的 Bilibili 稿件；请手动到创作中心查找。"
        )
    return lines, warnings


def prepare_replacement(video_id: str, history_file: Path = HISTORY_FILE, output_dir: Path = OUTPUT_DIR) -> str:
    history = load_history(history_file)
    record = find_history_record(video_id, history)
    if record is None:
        raise LookupError(
            f"在 {history_file} 中找不到 video_id={video_id} 的上传记录。请先运行 python3 audit_uploaded.py 确认目标视频。"
        )

    output_path = resolve_output_video(video_id, output_dir)
    if not output_path.exists():
        raise FileNotFoundError(
            f"找不到本地成品视频: {output_path}。请先重跑 pipeline 生成 output/{video_id}.mp4"
        )

    lines, warnings = build_checklist(video_id, record, output_path)
    if warnings:
        lines.extend(["", "Warnings:"])
        lines.extend(f"- {warning}" for warning in warnings)
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare a read-only Bilibili replacement checklist")
    parser.add_argument("video_id", help="Local YouTube video ID, for example G8DJHg428rQ")
    args = parser.parse_args()

    try:
        print(prepare_replacement(args.video_id), end="")
    except (FileNotFoundError, LookupError, json.JSONDecodeError) as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()