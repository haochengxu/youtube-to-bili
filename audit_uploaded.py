#!/usr/bin/env python3
"""Audit uploaded videos and local subtitle/output artifacts.

Usage:
  python3 audit_uploaded.py
  python3 audit_uploaded.py --json
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


SCRIPT_DIR = Path(__file__).parent
HISTORY_FILE = SCRIPT_DIR / "uploaded" / "history.json"
SUBTITLES_DIR = SCRIPT_DIR / "subtitles"
OUTPUT_DIR = SCRIPT_DIR / "output"


def srt_ts_to_ms(ts: str) -> int:
    ts = ts.strip().replace(",", ".")
    h, m, rest = ts.split(":")
    s, ms = rest.split(".")
    return int(h) * 3600000 + int(m) * 60000 + int(s) * 1000 + int(ms.ljust(3, "0")[:3])


def parse_srt(path: Path) -> list[dict]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8-sig")
    entries = []
    for block in re.split(r"\n{2,}", text.strip()):
        parts = block.strip().split("\n", 2)
        if len(parts) < 3 or not parts[0].strip().isdigit():
            continue
        m = re.match(r"(.+?)\s*-->\s*(.+)", parts[1].strip())
        if not m:
            continue
        content = re.sub(r"<[^>]+>", "", parts[2]).strip()
        entries.append({
            "index": parts[0].strip(),
            "start": srt_ts_to_ms(m.group(1)),
            "end": srt_ts_to_ms(m.group(2)),
            "text": content,
        })
    return entries


def count_timing_issues(entries: list[dict]) -> tuple[int, int]:
    invalid = 0
    overlaps = 0
    prev_end = None
    for entry in entries:
        if entry["end"] <= entry["start"]:
            invalid += 1
        if prev_end is not None and entry["start"] < prev_end:
            overlaps += 1
        prev_end = max(prev_end or 0, entry["end"])
    return invalid, overlaps


def ass_chinese_is_yellow(ass_text: str) -> bool:
    for line in ass_text.splitlines():
        if line.startswith("Style: Chinese,"):
            parts = [p.strip() for p in line.split(",")]
            return len(parts) > 3 and parts[3].upper() == "&H0000FFFF"
    return False


def audit_one(item: dict) -> dict:
    video_id = item.get("video_id", "")
    en_path = SUBTITLES_DIR / f"{video_id}.en.srt"
    zh_path = SUBTITLES_DIR / f"{video_id}.zh.srt"
    ass_path = SUBTITLES_DIR / f"{video_id}.bilingual.ass"
    output_candidates = [
        OUTPUT_DIR / f"{video_id}.mp4",
        OUTPUT_DIR / f"{video_id}_v2.mp4",
    ]
    output_path = next((p for p in output_candidates if p.exists()), None)

    en_entries = parse_srt(en_path)
    zh_entries = parse_srt(zh_path)
    en_invalid, en_overlaps = count_timing_issues(en_entries)
    zh_invalid, zh_overlaps = count_timing_issues(zh_entries)

    empty_zh = sum(1 for e in zh_entries if not e["text"].strip())
    long_en = sum(1 for e in en_entries if len(" ".join(e["text"].split())) > 100)
    long_zh = sum(1 for e in zh_entries if len("".join(e["text"].split())) > 60)

    ass_text = ass_path.read_text(encoding="utf-8-sig") if ass_path.exists() else ""
    chinese_yellow = ass_chinese_is_yellow(ass_text)

    issues = []
    if item.get("bvid") == "SKIPPED_PRIVATE":
        issues.append("skipped_private")
    if not en_path.exists():
        issues.append("missing_en_srt")
    if not zh_path.exists():
        issues.append("missing_zh_srt")
    if not ass_path.exists():
        issues.append("missing_ass")
    if not output_path:
        issues.append("missing_output")
    if en_entries and zh_entries and len(en_entries) != len(zh_entries):
        issues.append(f"count_mismatch:{len(en_entries)}vs{len(zh_entries)}")
    if empty_zh:
        issues.append(f"empty_zh:{empty_zh}")
    if en_invalid or zh_invalid:
        issues.append(f"invalid_timing:{en_invalid + zh_invalid}")
    if en_overlaps or zh_overlaps:
        issues.append(f"overlap:{en_overlaps + zh_overlaps}")
    if long_en:
        issues.append(f"long_en:{long_en}")
    if long_zh:
        issues.append(f"long_zh:{long_zh}")
    if ass_path.exists() and not chinese_yellow:
        issues.append("ass_chinese_not_yellow")

    if "skipped_private" in issues:
        action = "skip"
    elif any(i.startswith(("missing_", "count_mismatch", "empty_zh", "invalid_timing")) for i in issues):
        action = "redo"
    elif any(i.startswith(("overlap", "long_", "ass_chinese_not_yellow")) for i in issues):
        action = "review"
    else:
        action = "ok"

    return {
        "video_id": video_id,
        "bvid": item.get("bvid", ""),
        "title": item.get("title", ""),
        "action": action,
        "issues": issues,
        "counts": {
            "en": len(en_entries),
            "zh": len(zh_entries),
        },
        "paths": {
            "en": str(en_path) if en_path.exists() else "",
            "zh": str(zh_path) if zh_path.exists() else "",
            "ass": str(ass_path) if ass_path.exists() else "",
            "output": str(output_path) if output_path else "",
        },
    }


def load_history() -> list[dict]:
    if not HISTORY_FILE.exists():
        raise SystemExit(f"找不到历史记录: {HISTORY_FILE}")
    return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))


def print_report(results: list[dict]) -> None:
    totals = {"ok": 0, "review": 0, "redo": 0, "skip": 0}
    for result in results:
        totals[result["action"]] += 1

    print("Uploaded audit")
    print(
        f"  ok: {totals['ok']}  review: {totals['review']}  "
        f"redo: {totals['redo']}  skip: {totals['skip']}"
    )
    print()
    for result in results:
        issues = ", ".join(result["issues"]) if result["issues"] else "-"
        counts = result["counts"]
        print(
            f"[{result['action'].upper():6}] {result['video_id']} "
            f"en={counts['en']} zh={counts['zh']}  {issues}"
        )
        print(f"        {result['title'][:100]}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit uploaded video artifacts")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    args = parser.parse_args()

    results = [audit_one(item) for item in load_history()]
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print_report(results)


if __name__ == "__main__":
    main()
