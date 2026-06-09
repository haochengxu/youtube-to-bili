#!/usr/bin/env python3
"""Tests for learning summary generation."""

import tempfile
from pathlib import Path

from summarize_subtitles import clean_bilibili_description, extract_video_id, generate_summary, summary_output_path


EN_SRT = """1
00:00:00,000 --> 00:00:04,000
Awareness begins when we stop arguing with the moment.

2
00:04:00,000 --> 00:04:05,000
Real practice means feeling experience before naming it.

3
00:08:00,000 --> 00:08:05,000
Surrender is not passivity, it is relaxed clarity.
"""

ZH_SRT = """1
00:00:00,000 --> 00:00:04,000
当我们不再和当下争论，觉知就开始了。

2
00:04:00,000 --> 00:04:05,000
真正的练习，是先感受经验，再给它命名。

3
00:08:00,000 --> 00:08:05,000
臣服不是被动，而是放松而清明。
"""


def fake_runner(_prompt: str, timeout: int = 300) -> str:
    assert timeout == 300
    return """{
  "core_ideas": [
    "先回到直接经验，再解释发生了什么。",
    "练习的重点是放下对当下的抗拒。",
    "清明与放松可以同时存在。"
  ],
  "key_concepts": [
    {"concept": "觉知", "explanation": "直接知道当下正在发生什么。"},
    {"concept": "臣服", "explanation": "不再和经验对抗，但并非放弃行动。"}
  ],
  "bilibili_description": "这期内容围绕觉知、练习与臣服展开，提醒我们先回到直接经验，再解释发生了什么。",
  "chapters": [
    {"time": "00:00", "title": "停止和当下争论"},
    {"time": "04:00", "title": "先感受，再命名经验"}
  ]
}"""


def transcript_dump_runner(_prompt: str, timeout: int = 300) -> str:
    assert timeout == 300
    return (
        "Awareness begins when we stop arguing with the moment.\n"
        "Real practice means feeling experience before naming it.\n"
        "Surrender is not passivity, it is relaxed clarity."
    )


def test_extract_video_id():
    assert extract_video_id("subtitles/r2q_VN5beLs.en.srt") == "r2q_VN5beLs"
    assert extract_video_id("subtitles/r2q_VN5beLs.zh.srt") == "r2q_VN5beLs"


def test_summary_output_path_generation():
    assert summary_output_path("abc123", Path("summaries")) == Path("summaries/abc123.md")


def test_summary_markdown_does_not_copy_full_transcript():
    with tempfile.TemporaryDirectory() as tmpdir:
        workdir = Path(tmpdir)
        en_path = workdir / "demo123.en.srt"
        zh_path = workdir / "demo123.zh.srt"
        en_path.write_text(EN_SRT, encoding="utf-8")
        zh_path.write_text(ZH_SRT, encoding="utf-8")

        out_path = generate_summary(
            en_path,
            zh_path,
            title="Demo Title",
            url="https://youtube.com/watch?v=demo123",
            llm_runner=fake_runner,
            summaries_dir=workdir / "summaries",
        )
        markdown = out_path.read_text(encoding="utf-8")

        assert "# 学习摘要：Demo Title" in markdown
        assert "完整 transcript" not in markdown.lower()
        assert EN_SRT.strip() not in markdown


def test_non_json_response_is_sanitized():
    with tempfile.TemporaryDirectory() as tmpdir:
        workdir = Path(tmpdir)
        en_path = workdir / "demo456.en.srt"
        zh_path = workdir / "demo456.zh.srt"
        en_path.write_text(EN_SRT, encoding="utf-8")
        zh_path.write_text(ZH_SRT, encoding="utf-8")

        out_path = generate_summary(
            en_path,
            zh_path,
            llm_runner=transcript_dump_runner,
            summaries_dir=workdir / "summaries",
        )
        markdown = out_path.read_text(encoding="utf-8")

        assert "Awareness begins when we stop arguing with the moment." not in markdown
        assert "Real practice means feeling experience before naming it." not in markdown


def test_bilibili_description_removes_english_learning_framing():
    description = (
        "这期内容讨论如何面对经验。"
        "适合英语学习者练习抽象词汇。"
        "核心是先看见抗拒，再回到清明。"
    )
    cleaned = clean_bilibili_description(description)
    assert "英语学习者" not in cleaned
    assert "抽象词汇" not in cleaned
    assert "这期内容讨论如何面对经验。" in cleaned
    assert "核心是先看见抗拒，再回到清明。" in cleaned


def run_all_tests():
    tests = [
        test_extract_video_id,
        test_summary_output_path_generation,
        test_summary_markdown_does_not_copy_full_transcript,
        test_non_json_response_is_sanitized,
        test_bilibili_description_removes_english_learning_framing,
    ]
    for test in tests:
        test()
        print(f"✅ {test.__name__}")
    print(f"结果: {len(tests)} passed, 0 failed, {len(tests)} total")


if __name__ == "__main__":
    run_all_tests()
