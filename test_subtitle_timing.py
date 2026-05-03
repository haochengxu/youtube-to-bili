#!/usr/bin/env python3
"""
test_subtitle_timing.py — 用 Whisper 语音识别验证字幕时间是否对齐实际语音

思路：
1. 用 faster-whisper 对音频做词级时间戳识别
2. 对每条字幕，在 whisper 输出中找最佳匹配的词
3. 比较字幕 start 时间 vs 实际语音时间，计算延迟
4. 如果平均延迟 > 阈值，测试失败

用法：
    python3 test_subtitle_timing.py <video.mp4> <subtitle.srt> [--threshold 1.0]
"""

import sys
import re
from pathlib import Path
from difflib import SequenceMatcher


def parse_srt(path: str) -> list[dict]:
    """解析 SRT 文件"""
    text = Path(path).read_text(encoding='utf-8')
    blocks = re.split(r'\n{2,}', text.strip())
    entries = []
    for block in blocks:
        parts = block.strip().split('\n', 2)
        if len(parts) < 3:
            continue
        idx, ts_line = parts[0].strip(), parts[1].strip()
        if not idx.isdigit():
            continue
        m = re.match(r'(.+?)\s*-->\s*(.+)', ts_line)
        if not m:
            continue
        content = re.sub(r'<[^>]+>', '', parts[2].strip())
        content = ' '.join(content.split())

        def parse_ts(ts_str):
            ts_clean = ts_str.strip().replace(',', '.')
            p = ts_clean.split(':')
            h, mi = int(p[0]), int(p[1])
            s_parts = p[2].split('.')
            sec = int(s_parts[0])
            ms = int(s_parts[1].ljust(3, '0')[:3]) if len(s_parts) > 1 else 0
            return h*3600000 + mi*60000 + sec*1000 + ms

        start = parse_ts(m.group(1))
        end = parse_ts(m.group(2))
        entries.append({'start': start, 'end': end, 'text': content})
    return entries


def whisper_transcribe(video_path: str, model_size: str = "base") -> list[dict]:
    """用 faster-whisper 做词级时间戳识别"""
    from faster_whisper import WhisperModel
    import os

    # 抽取音频
    audio_path = "/tmp/_whisper_audio.wav"
    os.system(f'ffmpeg -y -i "{video_path}" -vn -acodec pcm_s16le -ar 16000 -ac 1 "{audio_path}" 2>/dev/null')

    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, info = model.transcribe(audio_path, language="en", word_timestamps=True)

    words = []
    for segment in segments:
        for w in segment.words:
            words.append({
                'word': w.word.strip(),
                'start': int(w.start * 1000),
                'end': int(w.end * 1000),
            })

    return words


def find_best_match(sub_text: str, words: list[dict], search_range_ms: int = 10000) -> dict:
    """
    在 whisper 词列表中找与 sub_text 最匹配的片段。
    返回 {'whisper_start': ms, 'whisper_end': ms, 'match_ratio': float}
    """
    sub_words = sub_text.lower().split()
    if not sub_words:
        return None

    best_ratio = 0
    best_start = 0
    best_end = 0

    # 滑动窗口匹配
    for i in range(len(words)):
        window = words[i:i + len(sub_words) + 2]  # 允许多/少 2 个词
        window_text = ' '.join(w['word'].lower() for w in window)
        ratio = SequenceMatcher(None, ' '.join(sub_words), window_text).ratio()

        if ratio > best_ratio:
            best_ratio = ratio
            best_start = window[0]['start']
            best_end = window[-1]['end']

    return {
        'whisper_start': best_start,
        'whisper_end': best_end,
        'match_ratio': best_ratio,
    }


def validate_timing(video_path: str, srt_path: str, threshold_ms: float = 1500):
    """
    验证字幕时间是否对齐实际语音。
    返回 (passed: bool, report: str)
    """
    print(f"🎤 Whisper 转录中: {video_path}")
    words = whisper_transcribe(video_path, "base")
    print(f"   识别到 {len(words)} 个词")

    subtitles = parse_srt(srt_path)
    print(f"📝 字幕: {len(subtitles)} 条\n")

    delays = []
    results = []

    for i, sub in enumerate(subtitles):
        match = find_best_match(sub['text'], words)
        if match is None:
            continue

        delay = sub['start'] - match['whisper_start']
        delays.append(delay)

        status = "✅" if abs(delay) <= threshold_ms else "❌"
        results.append({
            'idx': i,
            'sub_start': sub['start'],
            'whisper_start': match['whisper_start'],
            'delay': delay,
            'text': sub['text'][:50],
            'match_ratio': match['match_ratio'],
            'status': status,
        })

    # 统计
    if not delays:
        return False, "没有匹配的字幕"

    avg_delay = sum(delays) / len(delays)
    max_delay = max(delays)
    min_delay = min(delays)
    late_count = sum(1 for d in delays if d > threshold_ms)
    early_count = sum(1 for d in delays if d < -threshold_ms)

    report_lines = []
    report_lines.append("=" * 60)
    report_lines.append("字幕时间验证报告")
    report_lines.append("=" * 60)
    report_lines.append(f"总字幕数: {len(subtitles)}")
    report_lines.append(f"匹配数:   {len(delays)}")
    report_lines.append(f"平均延迟: {avg_delay:+.0f}ms")
    report_lines.append(f"最大延迟: {max_delay:+.0f}ms")
    report_lines.append(f"最小延迟: {min_delay:+.0f}ms")
    report_lines.append(f"偏晚 >{threshold_ms}ms: {late_count} 条 ({late_count/len(delays)*100:.0f}%)")
    report_lines.append(f"偏早 >{threshold_ms}ms: {early_count} 条 ({early_count/len(delays)*100:.0f}%)")
    report_lines.append("")

    # 显示问题最大的几条
    bad_results = [r for r in results if abs(r['delay']) > threshold_ms]
    bad_results.sort(key=lambda r: abs(r['delay']), reverse=True)

    if bad_results:
        report_lines.append(f"⚠️  延迟最大的 {min(10, len(bad_results))} 条:")
        report_lines.append("-" * 60)
        for r in bad_results[:10]:
            report_lines.append(
                f"  {r['status']} #{r['idx']:3d} | "
                f"字幕={r['sub_start']/1000:6.1f}s  "
                f"语音={r['whisper_start']/1000:6.1f}s  "
                f"延迟={r['delay']:+6.0f}ms  "
                f"匹配={r['match_ratio']:.0%}"
            )
            report_lines.append(f"         {r['text']}")
        report_lines.append("")

    # 判断通过/失败
    passed = avg_delay < threshold_ms and late_count < len(delays) * 0.3
    report_lines.append(f"结果: {'✅ PASS' if passed else '❌ FAIL'}")
    report_lines.append(f"  (平均延迟 {avg_delay:+.0f}ms, "
                        f"{late_count}/{len(delays)} 条偏晚)")

    return passed, '\n'.join(report_lines)


def main():
    if len(sys.argv) < 3:
        print("用法: python3 test_subtitle_timing.py <video.mp4> <subtitle.srt> [--threshold 1.5]")
        sys.exit(1)

    video_path = sys.argv[1]
    srt_path = sys.argv[2]
    threshold = 1500

    for i, arg in enumerate(sys.argv):
        if arg == '--threshold' and i + 1 < len(sys.argv):
            threshold = float(sys.argv[i + 1]) * 1000

    if not Path(video_path).exists():
        print(f"视频不存在: {video_path}")
        sys.exit(1)
    if not Path(srt_path).exists():
        print(f"字幕不存在: {srt_path}")
        sys.exit(1)

    passed, report = validate_timing(video_path, srt_path, threshold)
    print(report)
    sys.exit(0 if passed else 1)


if __name__ == '__main__':
    main()
