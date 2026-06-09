#!/usr/bin/env python3
"""Generate a compact Markdown learning summary from bilingual subtitles."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

from translator_cli import TranslatorError, run_llm


SCRIPT_DIR = Path(__file__).parent
SUMMARIES_DIR = SCRIPT_DIR / "summaries"
STOP_WORDS = {
    "about", "after", "again", "also", "because", "being", "could", "first", "from", "have",
    "into", "just", "like", "more", "most", "only", "other", "really", "should", "still",
    "their", "there", "these", "thing", "think", "those", "through", "very", "what", "when",
    "which", "while", "with", "would", "your", "that", "this", "they", "them", "then", "than",
}
DESCRIPTION_FORBIDDEN_PHRASES = (
    "英语学习",
    "英语学习者",
    "词汇练习",
    "听力练习",
    "练习英语",
    "英文表达",
    "高频词",
)


def extract_video_id(path: str | Path) -> str:
    name = Path(path).name
    for suffix in (".en.srt", ".zh.srt", ".srt"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return Path(path).stem


def summary_output_path(video_id: str, summaries_dir: Path = SUMMARIES_DIR) -> Path:
    return summaries_dir / f"{video_id}.md"


def srt_timestamp_to_ms(timestamp: str) -> int:
    hours_str, minutes_str, seconds_part = timestamp.split(":")
    seconds_str, millis_str = seconds_part.split(",")
    hours = int(hours_str)
    minutes = int(minutes_str)
    seconds = int(seconds_str)
    ms = int(millis_str)
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + ms


def parse_srt(text: str) -> list[dict]:
    blocks = re.split(r"\n\n+", text.strip())
    entries = []
    for block in blocks:
        parts = block.strip().split("\n", 2)
        if len(parts) < 3 or not parts[0].strip().isdigit():
            continue
        timing = parts[1].strip()
        match = re.match(r"(.+?)\s*-->\s*(.+)", timing)
        if not match:
            continue
        entries.append(
            {
                "index": int(parts[0].strip()),
                "start": match.group(1).strip(),
                "end": match.group(2).strip(),
                "start_ms": srt_timestamp_to_ms(match.group(1).strip()),
                "end_ms": srt_timestamp_to_ms(match.group(2).strip()),
                "text": re.sub(r"\s+", " ", parts[2].strip()),
            }
        )
    return entries


def chapter_bucket_minutes(duration_minutes: float) -> int:
    if duration_minutes <= 15:
        return 3
    if duration_minutes <= 35:
        return 5
    return 8


def format_chapter_time(start_ms: int) -> str:
    total_seconds = max(0, start_ms // 1000)
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def extract_candidate_keywords(entries: list[dict], limit: int = 12) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z'-]{3,}", " ".join(entry["text"] for entry in entries))
    counts = Counter(word.lower() for word in words if word.lower() not in STOP_WORDS)
    return [word for word, _count in counts.most_common(limit)]


def build_transcript_digest(en_entries: list[dict], zh_entries: list[dict]) -> tuple[list[dict], int]:
    if not en_entries:
        return [], 5

    duration_minutes = max(1.0, en_entries[-1]["end_ms"] / 60000)
    bucket_minutes = chapter_bucket_minutes(duration_minutes)
    bucket_ms = bucket_minutes * 60 * 1000
    zh_map = {entry["index"]: entry for entry in zh_entries}
    buckets: dict[int, list[dict]] = {}
    for entry in en_entries:
        bucket_index = entry["start_ms"] // bucket_ms
        buckets.setdefault(bucket_index, [])
        if len(buckets[bucket_index]) >= 3:
            continue
        zh_entry = zh_map.get(entry["index"])
        buckets[bucket_index].append(
            {
                "time": format_chapter_time(entry["start_ms"]),
                "en": entry["text"][:180],
                "zh": (zh_entry["text"][:120] if zh_entry else ""),
            }
        )

    digest = []
    for bucket_index in sorted(buckets):
        start_ms = bucket_index * bucket_ms
        digest.append(
            {
                "chapter_start": format_chapter_time(start_ms),
                "excerpt_pairs": buckets[bucket_index],
            }
        )
    return digest, bucket_minutes


def build_summary_prompt(video_id: str, en_entries: list[dict], zh_entries: list[dict], title: str = "", url: str = "") -> str:
    digest, bucket_minutes = build_transcript_digest(en_entries, zh_entries)
    keywords = extract_candidate_keywords(en_entries)
    payload = {
        "video_id": video_id,
        "title": title,
        "url": url,
        "chapter_bucket_minutes": bucket_minutes,
        "candidate_keywords": keywords,
        "transcript_digest": digest,
    }
    return (
        "你是一个内容向视频编辑，请根据下面的字幕摘要生成紧凑的中文内容笔记。\n"
        "定位：这是给观众理解视频思想的内容摘要，不是英语学习材料。\n"
        "要求：\n"
        "1. 只输出 JSON，不要输出 markdown 代码块。\n"
        "2. 返回字段必须包含 core_ideas, key_concepts, bilibili_description。\n"
        "3. core_ideas 为 3 到 5 条，每条一句话。\n"
        "4. key_concepts 为 4 到 8 条，每条包含 concept, explanation；concept 用中文或中英混合均可。\n"
        "5. chapters 可选，按给定时间桶总结，不要抄原字幕。\n"
        "6. 不要输出完整 transcript，不要逐句复述。\n"
        "7. bilibili_description 聚焦视频内容本身，不要写英语学习、词汇练习、听力练习、适合英语学习者。\n\n"
        f"摘要输入：\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def parse_summary_response(response: str) -> dict:
    try:
        data = json.loads(response)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    compact = re.sub(r"\s+", " ", response).strip()
    return {
        "core_ideas": ["模型未返回结构化总结，需人工复查。"],
        "key_concepts": [],
        "bilibili_description": compact[:180],
        "chapters": [],
    }


def clean_bilibili_description(text: str) -> str:
    """Remove learning-English framing from content summaries."""
    compact = re.sub(r"\s+", " ", str(text or "")).strip()
    if not compact:
        return ""

    parts = re.split(r"(?<=[。！？!?])\s*", compact)
    kept = [
        part.strip()
        for part in parts
        if part.strip() and not any(phrase in part for phrase in DESCRIPTION_FORBIDDEN_PHRASES)
    ]
    cleaned = "".join(kept).strip()
    return cleaned or compact


def render_summary_markdown(video_id: str, title: str, url: str, summary_data: dict) -> str:
    lines = [f"# 学习摘要：{title or video_id}", ""]
    if title:
        lines.append(f"- 视频标题：{title}")
    if url:
        lines.append(f"- 原始链接：{url}")
    lines.append(f"- 视频 ID：{video_id}")
    lines.append("")

    core_ideas = summary_data.get("core_ideas") or []
    lines.append("## Core Ideas")
    for idea in core_ideas[:5]:
        lines.append(f"- {str(idea).strip()}")
    if not core_ideas:
        lines.append("- 暂无结构化要点，请人工复查。")
    lines.append("")

    lines.append("## Key Concepts")
    lines.append("| 概念 | 说明 |")
    lines.append("| --- | --- |")
    key_concepts = summary_data.get("key_concepts") or summary_data.get("keywords") or []
    if key_concepts:
        for item in key_concepts[:8]:
            concept = str(item.get("concept") or item.get("zh") or item.get("en") or "").strip()
            explanation = str(item.get("explanation", "")).strip()
            lines.append(f"| {concept} | {explanation} |")
    else:
        lines.append("| - | 暂无关键概念 |")
    lines.append("")

    lines.append("## Bilibili Description")
    lines.append(clean_bilibili_description(summary_data.get("bilibili_description", "")) or "暂无摘要描述。")
    lines.append("")

    chapters = summary_data.get("chapters") or []
    if chapters:
        lines.append("## Chapters")
        for chapter in chapters:
            timestamp = str(chapter.get("time", "")).strip()
            chapter_title = str(chapter.get("title", "")).strip()
            if timestamp or chapter_title:
                lines.append(f"- {timestamp} {chapter_title}".strip())
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def transcript_dump_detected(markdown_text: str, en_entries: list[dict]) -> bool:
    long_lines = [entry["text"] for entry in en_entries if len(entry["text"].split()) >= 8]
    matches = sum(1 for line in long_lines if line and line in markdown_text)
    return matches >= 3


def generate_summary(
    en_path: Path,
    zh_path: Path,
    title: str = "",
    url: str = "",
    llm_runner=run_llm,
    summaries_dir: Path = SUMMARIES_DIR,
) -> Path:
    en_entries = parse_srt(en_path.read_text(encoding="utf-8"))
    zh_entries = parse_srt(zh_path.read_text(encoding="utf-8"))
    video_id = extract_video_id(en_path)
    prompt = build_summary_prompt(video_id, en_entries, zh_entries, title=title, url=url)
    response = llm_runner(prompt, timeout=300)
    summary_data = parse_summary_response(response)
    markdown = render_summary_markdown(video_id, title, url, summary_data)
    if transcript_dump_detected(markdown, en_entries):
        summary_data = {
            "core_ideas": summary_data.get("core_ideas") or ["模型输出包含过多原文，已降级为简短摘要。"],
            "key_concepts": summary_data.get("key_concepts") or summary_data.get("keywords") or [],
            "bilibili_description": "该视频摘要已生成，但模型输出包含过长原文，建议人工复查后再发布。",
            "chapters": summary_data.get("chapters") or [],
        }
        markdown = render_summary_markdown(video_id, title, url, summary_data)

    output_path = summary_output_path(video_id, summaries_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate learning summary markdown from bilingual subtitles")
    parser.add_argument("en_srt")
    parser.add_argument("zh_srt")
    parser.add_argument("--title", default="")
    parser.add_argument("--url", default="")
    args = parser.parse_args()

    en_path = Path(args.en_srt)
    zh_path = Path(args.zh_srt)
    for path in (en_path, zh_path):
        if not path.exists():
            print(f"文件不存在: {path}", file=sys.stderr)
            sys.exit(1)

    try:
        out_path = generate_summary(en_path, zh_path, title=args.title, url=args.url)
    except TranslatorError as exc:
        print(f"总结失败: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"✅ 学习摘要已写入: {out_path}")


if __name__ == "__main__":
    main()
