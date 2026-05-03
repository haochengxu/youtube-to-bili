#!/usr/bin/env python3
"""
test_merge_srt.py — merge_srt.py 的单元测试

测试用例覆盖：
1. 时间戳单调递增（无回退）
2. 无重叠（每句 end <= 下一句 start）
3. 最小持续时间（>= 500ms）
4. 字符数限制（不超过 max_chars）
5. YouTube 滚动字幕的特殊场景
"""

import sys
import tempfile
from pathlib import Path

# 确保能导入 merge_srt
sys.path.insert(0, str(Path(__file__).parent))

from merge_srt import (
    parse_srt, merge_entries, fix_overlaps, build_srt,
    get_char_limits, group_by_gap, split_group_into_sentences
)


# ──────────────────────────────────────────────
# 辅助函数
# ──────────────────────────────────────────────

def make_srt(entries: list[dict]) -> str:
    """从 entries 列表生成 SRT 字符串"""
    blocks = []
    for i, e in enumerate(entries, 1):
        ts = f"{ms_to_ts(e['start'])} --> {ms_to_ts(e['end'])}"
        blocks.append(f"{i}\n{ts}\n{e['text']}")
    return '\n\n'.join(blocks) + '\n'


def ms_to_ts(ms: int) -> str:
    """ms → 00:01:23,456"""
    ms = max(0, ms)
    h = ms // 3600000; ms %= 3600000
    m = ms // 60000;   ms %= 60000
    s = ms // 1000;    rem = ms % 1000
    return f"{h:02d}:{m:02d}:{s:02d},{rem:03d}"


def process_entries(entries: list[dict], max_chars: int = 80) -> list[dict]:
    """完整的处理流程：merge → fix_overlaps"""
    sentences = merge_entries(entries, max_chars, int(max_chars * 0.75))
    sentences = fix_overlaps(sentences)
    return sentences


# ──────────────────────────────────────────────
# 测试断言
# ──────────────────────────────────────────────

def assert_monotonic(sentences: list[dict]):
    """断言时间戳严格单调递增"""
    for i in range(1, len(sentences)):
        assert sentences[i]['start'] >= sentences[i-1]['end'], \
            f"时间回退: #{i-1} end={sentences[i-1]['end']}ms > #{i} start={sentences[i]['start']}ms\n" \
            f"  #{i-1}: {sentences[i-1]['text'][:50]}\n" \
            f"  #{i}: {sentences[i]['text'][:50]}"


def assert_no_overlap(sentences: list[dict]):
    """断言无重叠"""
    for i in range(len(sentences) - 1):
        assert sentences[i]['end'] <= sentences[i+1]['start'], \
            f"重叠: #{i} end={sentences[i]['end']}ms > #{i+1} start={sentences[i+1]['start']}ms\n" \
            f"  #{i}: {sentences[i]['text'][:50]}\n" \
            f"  #{i+1}: {sentences[i+1]['text'][:50]}"


def assert_min_duration(sentences: list[dict], min_ms: int = 500):
    """断言最小持续时间"""
    for i, s in enumerate(sentences):
        dur = s['end'] - s['start']
        assert dur >= min_ms, \
            f"持续时间太短: #{i} {dur}ms < {min_ms}ms, text={s['text'][:50]}"


def assert_max_chars(sentences: list[dict], max_chars: int):
    """断言每句不超过 max_chars"""
    for i, s in enumerate(sentences):
        assert len(s['text']) <= max_chars, \
            f"超长: #{i} {len(s['text'])} chars > {max_chars}, text={s['text'][:80]}"


def assert_positive_time(sentences: list[dict]):
    """断言所有时间 >= 0"""
    for i, s in enumerate(sentences):
        assert s['start'] >= 0, f"负时间: #{i} start={s['start']}"
        assert s['end'] >= 0, f"负时间: #{i} end={s['end']}"


# ──────────────────────────────────────────────
# 测试用例
# ──────────────────────────────────────────────

def test_basic_non_overlapping():
    """基本场景：不重叠的 entries"""
    entries = [
        {'start': 0, 'end': 3000, 'text': 'Hello world.'},
        {'start': 3500, 'end': 6000, 'text': 'How are you?'},
        {'start': 6500, 'end': 9000, 'text': 'I am fine.'},
    ]
    sentences = process_entries(entries)
    assert_monotonic(sentences)
    assert_no_overlap(sentences)
    assert_min_duration(sentences)
    assert len(sentences) >= 3
    print("✅ test_basic_non_overlapping")


def test_youtube_rolling_subtitles():
    """YouTube 滚动字幕：entries 大量重叠"""
    entries = [
        {'start': 400, 'end': 12719, 'text': 'What am I here right now?'},
        {'start': 7279, 'end': 15360, 'text': 'What is true right now?'},
        {'start': 12719, 'end': 16960, 'text': 'Everything is here.'},
        {'start': 15360, 'end': 20320, 'text': 'Because as soon as you get it,'},
        {'start': 16960, 'end': 23199, 'text': 'you realize everything changes.'},
    ]
    sentences = process_entries(entries)
    assert_monotonic(sentences)
    assert_no_overlap(sentences)
    assert_min_duration(sentences)
    assert_positive_time(sentences)
    # 第一句应该从 ~400ms 开始，不是从后面
    assert sentences[0]['start'] <= 1000, \
        f"第一句开始太晚: {sentences[0]['start']}ms"
    print("✅ test_youtube_rolling_subtitles")


def test_identical_timestamps():
    """所有 entries 时间完全相同（YouTube 某些字幕的极端情况）"""
    entries = [
        {'start': 1000, 'end': 1500, 'text': 'Hello'},
        {'start': 1000, 'end': 1500, 'text': 'world'},
        {'start': 1000, 'end': 1500, 'text': 'how are you?'},
        {'start': 1000, 'end': 1500, 'text': 'I am fine.'},
    ]
    sentences = process_entries(entries)
    assert_monotonic(sentences)
    assert_no_overlap(sentences)
    assert_min_duration(sentences)
    print("✅ test_identical_timestamps")


def test_long_entries_spanning_minutes():
    """长视频：entries 跨越多分钟"""
    entries = [
        {'start': 0, 'end': 60000, 'text': 'This is a very long sentence that spans an entire minute of the video.'},
        {'start': 30000, 'end': 120000, 'text': 'And this overlaps with it significantly.'},
        {'start': 90000, 'end': 180000, 'text': 'Finally this covers the last section.'},
    ]
    sentences = process_entries(entries)
    assert_monotonic(sentences)
    assert_no_overlap(sentences)
    assert_min_duration(sentences)
    # 总时长应该覆盖到 ~180s
    assert sentences[-1]['end'] >= 150000, \
        f"最后一句结束太早: {sentences[-1]['end']}ms"
    print("✅ test_long_entries_spanning_minutes")


def test_short_entries_rapid_fire():
    """快速连续的短 entries"""
    entries = [
        {'start': i * 500, 'end': i * 500 + 600, 'text': f'word{i}'}
        for i in range(20)
    ]
    sentences = process_entries(entries, max_chars=30)
    assert_monotonic(sentences)
    assert_no_overlap(sentences)
    assert_min_duration(sentences)
    print("✅ test_short_entries_rapid_fire")


def test_max_chars_enforcement():
    """确保不超长"""
    long_text = 'This is a very long sentence that should be split into multiple lines because it exceeds the character limit.'
    entries = [
        {'start': 0, 'end': 10000, 'text': long_text},
        {'start': 10000, 'end': 20000, 'text': 'Short.'},
    ]
    max_chars = 40
    sentences = process_entries(entries, max_chars=max_chars)
    assert_max_chars(sentences, max_chars)
    assert_monotonic(sentences)
    assert_no_overlap(sentences)
    print("✅ test_max_chars_enforcement")


def test_single_entry():
    """只有一个 entry"""
    entries = [
        {'start': 1000, 'end': 5000, 'text': 'Hello world.'},
    ]
    sentences = process_entries(entries)
    assert len(sentences) >= 1
    assert_monotonic(sentences)
    assert_min_duration(sentences)
    print("✅ test_single_entry")


def test_empty_entries():
    """空 entries"""
    entries = []
    sentences = process_entries(entries)
    assert len(sentences) == 0
    print("✅ test_empty_entries")


def test_nltk_sentence_splitting():
    """验证 nltk 正确断句"""
    entries = [
        {'start': 0, 'end': 10000, 'text': 'First sentence. Second sentence. Third one too.'},
    ]
    sentences = process_entries(entries)
    # 应该被 nltk 拆成至少 2 句
    assert len(sentences) >= 2, f"Expected >= 2 sentences, got {len(sentences)}"
    assert_monotonic(sentences)
    assert_no_overlap(sentences)
    print("✅ test_nltk_sentence_splitting")


def test_video_width_char_limits():
    """测试不同视频宽度的字符限制"""
    # 宽屏
    max_w, ideal_w = get_char_limits(1920)
    assert max_w == 80, f"1920px: expected max=80, got {max_w}"
    
    # 竖屏（最小值 20）
    max_v, ideal_v = get_char_limits(454)
    assert max_v == 20, f"454px: expected max=20, got {max_v}"
    
    # 超窄
    max_n, ideal_n = get_char_limits(200)
    assert max_n == 20, f"200px: expected max=20, got {max_n}"  # 最小值 20
    
    print("✅ test_video_width_char_limits")


def test_gap_threshold_grouping():
    """测试语音停顿分组"""
    entries = [
        # 第一组：连续说话
        {'start': 0, 'end': 2000, 'text': 'Hello'},
        {'start': 2100, 'end': 4000, 'text': 'world'},
        {'start': 4100, 'end': 6000, 'text': 'how are you'},
        # 停顿 1 秒
        # 第二组
        {'start': 7000, 'end': 9000, 'text': 'I am fine'},
        {'start': 9100, 'end': 11000, 'text': 'thanks'},
    ]
    groups = group_by_gap(entries)
    assert len(groups) == 2, f"Expected 2 groups, got {len(groups)}"
    assert len(groups[0]) == 3
    assert len(groups[1]) == 2
    print("✅ test_gap_threshold_grouping")


def test_real_world_short_video():
    """模拟真实短视频的 YouTube 字幕格式"""
    # 类似 YXvxSwXEj3E 的格式
    entries = [
        {'start': 400, 'end': 12719, 'text': 'What am I here right now? What is true'},
        {'start': 7279, 'end': 15360, 'text': 'right now? Everything is contained'},
        {'start': 12719, 'end': 16960, 'text': 'now to nothing more.'},
        {'start': 15360, 'end': 20320, 'text': 'Because as soon as you get now,'},
        {'start': 16960, 'end': 23199, 'text': 'you realize now everything changes.'},
        {'start': 20320, 'end': 26640, 'text': 'For some people it might be nice.'},
        {'start': 23199, 'end': 28720, 'text': 'Some people it might be terrible.'},
        {'start': 26640, 'end': 30320, 'text': 'Some people it might be in between.'},
    ]
    max_chars = 45  # 模拟 1080px 宽度
    sentences = process_entries(entries, max_chars)
    
    assert_monotonic(sentences)
    assert_no_overlap(sentences)
    assert_min_duration(sentences)
    assert_positive_time(sentences)
    assert_max_chars(sentences, max_chars)
    
    # 第一句应该在视频开头（< 2s），不是在中间
    assert sentences[0]['start'] < 2000, \
        f"第一句开始太晚: {sentences[0]['start']}ms"
    
    # 最后一句应该覆盖到视频后半段
    assert sentences[-1]['end'] > 25000, \
        f"最后一句结束太早: {sentences[-1]['end']}ms"
    
    print(f"✅ test_real_world_short_video ({len(sentences)} sentences)")


def test_real_world_long_video():
    """模拟真实长视频的 YouTube 字幕格式（多组）"""
    entries = []
    # 第一组：0-30s
    for i in range(10):
        start = i * 3000
        entries.append({
            'start': start,
            'end': start + 5000,
            'text': f'This is sentence number {i+1} in the first group.'
        })
    # 停顿 2 秒
    # 第二组：34-62s
    for i in range(10):
        start = 34000 + i * 3000
        entries.append({
            'start': start,
            'end': start + 5000,
            'text': f'This is sentence number {i+1} in the second group.'
        })
    
    sentences = process_entries(entries, max_chars=80)
    assert_monotonic(sentences)
    assert_no_overlap(sentences)
    assert_min_duration(sentences)
    assert_positive_time(sentences)
    
    # 应该有两组
    groups = group_by_gap(entries)
    assert len(groups) == 2, f"Expected 2 groups, got {len(groups)}"
    
    print(f"✅ test_real_world_long_video ({len(sentences)} sentences)")


# ──────────────────────────────────────────────
# 运行所有测试
# ──────────────────────────────────────────────

def run_all_tests():
    tests = [
        test_basic_non_overlapping,
        test_youtube_rolling_subtitles,
        test_identical_timestamps,
        test_long_entries_spanning_minutes,
        test_short_entries_rapid_fire,
        test_max_chars_enforcement,
        test_single_entry,
        test_empty_entries,
        test_nltk_sentence_splitting,
        test_video_width_char_limits,
        test_gap_threshold_grouping,
        test_real_world_short_video,
        test_real_world_long_video,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"❌ {test.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"💥 {test.__name__}: {type(e).__name__}: {e}")
            failed += 1
    
    print(f"\n{'='*50}")
    print(f"结果: {passed} passed, {failed} failed, {passed + failed} total")
    
    if failed > 0:
        sys.exit(1)
    else:
        print("🎉 所有测试通过！")


if __name__ == '__main__':
    run_all_tests()
