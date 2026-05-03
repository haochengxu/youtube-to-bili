#!/usr/bin/env python3
"""
merge_srt.py — 合并 YouTube 滚动式碎片字幕 → 自然句子字幕

YouTube 自动字幕是"滚动式"：每段只有几个词，且时间段互相重叠。
本脚本：先按语音停顿分组（间隔 > 500ms），再用 nltk 在组内按自然句子断句。

时间戳策略：
  - start = 句子第一个条目的 start（第一个词开始说的时间）
  - end   = 下一句第一个条目的 start（或最后一句最后一个条目的 end）

用法: python3 merge_srt.py <input.srt> <output.srt>
      python3 merge_srt.py <input.srt>   # 原地覆盖
"""

import sys
import re
from pathlib import Path

import nltk
try:
    nltk.data.find('tokenizers/punkt_tab')
except LookupError:
    nltk.download('punkt_tab', quiet=True)
from nltk.tokenize import sent_tokenize


def srt_ts_to_ms(ts: str) -> int:
    """00:01:23,456 → ms"""
    ts = ts.strip().replace(',', '.')
    h, m, rest = ts.split(':')
    s, ms_str = rest.split('.')
    ms_str = ms_str.ljust(3, '0')[:3]
    return int(h) * 3600000 + int(m) * 60000 + int(s) * 1000 + int(ms_str)


def ms_to_srt_ts(ms: int) -> str:
    """ms → 00:01:23,456"""
    ms = max(0, ms)
    h = ms // 3600000; ms %= 3600000
    m = ms // 60000;   ms %= 60000
    s = ms // 1000;    rem = ms % 1000
    return f"{h:02d}:{m:02d}:{s:02d},{rem:03d}"


def parse_srt(text: str) -> list[dict]:
    blocks = re.split(r'\n{2,}', text.strip())
    entries = []
    for block in blocks:
        parts = block.strip().split('\n', 2)
        if len(parts) < 3:
            continue
        idx, ts_line = parts[0].strip(), parts[1].strip()
        content = parts[2].strip() if len(parts) > 2 else ''
        if not idx.isdigit():
            continue
        m = re.match(r'(.+?)\s*-->\s*(.+)', ts_line)
        if not m:
            continue
        content = re.sub(r'<[^>]+>', '', content).strip()
        content = ' '.join(content.split())
        entries.append({
            'start': srt_ts_to_ms(m.group(1)),
            'end':   srt_ts_to_ms(m.group(2)),
            'text':  content,
        })
    entries.sort(key=lambda e: e['start'])
    return entries


GAP_THRESHOLD_MS = 500     # 间隔 > 500ms 视为语音停顿
MAX_SENTENCE_CHARS = 100   # 单句超过此长度时强制再拆（默认值，会被视频宽度覆盖）

# 根据视频宽度计算字幕字符数限制
def get_char_limits(width: int) -> tuple[int, int]:
    """返回 (MAX_CHARS, IDEAL_CHARS) 根据视频宽度"""
    # 每个字符大约占 24px 宽度（Arial/PingFang）
    max_c = max(20, int(width / 24))
    ideal_c = max(15, int(max_c * 0.75))
    return max_c, ideal_c


def group_by_gap(entries: list[dict]) -> list[list[dict]]:
    """
    按语音停顿分组：两条之间的间隔 > GAP_THRESHOLD_MS 则分为不同组。
    """
    if not entries:
        return []

    groups = []
    current = [entries[0]]

    for e in entries[1:]:
        prev_end = current[-1]['end']
        gap = e['start'] - prev_end
        if gap > GAP_THRESHOLD_MS:
            groups.append(current)
            current = [e]
        else:
            current.append(e)

    if current:
        groups.append(current)

    return groups


def _build_char_time_map(group: list[dict]) -> list[tuple[int, int, int, int]]:
    """
    构建字符位置→时间映射表。
    返回 [(char_start, char_end, time_start_ms, time_end_ms), ...] 每个 entry 一条。
    """
    mapping = []
    offset = 0
    for e in group:
        char_start = offset
        char_end = offset + len(e['text'])
        mapping.append((char_start, char_end, e['start'], e['end']))
        offset = char_end + 1  # +1 for the space join
    return mapping


def _char_to_ms(char_pos: int, mapping: list[tuple[int, int, int, int]]) -> int:
    """通过字符位置线性插值估算时间戳(ms)。"""
    for cs, ce, ts, te in mapping:
        if cs <= char_pos <= ce:
            length = ce - cs
            if length <= 0:
                return ts
            ratio = (char_pos - cs) / length
            return int(ts + ratio * (te - ts))
    # 超出范围：返回最近的时间
    if char_pos <= 0:
        return mapping[0][2]
    return mapping[-1][3]


def split_group_into_sentences(group: list[dict], max_chars: int = 100, ideal_chars: int = 75) -> list[dict]:
    """
    用 nltk.sent_tokenize 在一个语音段内按自然句子断句。
    通过字符位置线性插值映射到精确时间戳（解决 YouTube 滚动字幕重叠问题）。
    """
    if not group:
        return []

    full_text = ' '.join(e['text'] for e in group)
    raw_sentences = sent_tokenize(full_text)

    # 构建字符→时间映射
    char_map = _build_char_time_map(group)

    sentences = []
    char_pos = 0

    for sent_text in raw_sentences:
        sent_text = sent_text.strip()
        if not sent_text:
            continue

        sent_start_in_text = full_text.find(sent_text, char_pos)
        if sent_start_in_text == -1:
            sent_start_in_text = char_pos
        sent_end_in_text = sent_start_in_text + len(sent_text)

        start_ms = _char_to_ms(sent_start_in_text, char_map)
        end_ms = _char_to_ms(sent_end_in_text, char_map)

        # 确保最小持续时间 500ms
        if end_ms - start_ms < 500:
            end_ms = start_ms + 500

        # 如果单句太长，用标点强制再拆
        if len(sent_text) > max_chars:
            # 估算对应的 entry 范围用于 force_split
            entry_start_idx = 0
            entry_end_idx = len(group) - 1
            offset = 0
            for i, e in enumerate(group):
                e_end = offset + len(e['text'])
                if offset <= sent_start_in_text <= e_end:
                    entry_start_idx = i
                if offset <= sent_end_in_text <= e_end:
                    entry_end_idx = i
                    break
                offset = e_end + 1
            sub_sentences = _force_split_long_sentence(
                sent_text, group[entry_start_idx:entry_end_idx + 1], max_chars
            )
            # 修正 force_split 子句的时间范围，保证在 [start_ms, end_ms] 内
            if sub_sentences:
                total_chars = sum(len(s['text']) for s in sub_sentences)
                t = start_ms
                for si, ss in enumerate(sub_sentences):
                    if si == len(sub_sentences) - 1:
                        ss['start'] = int(t)
                        ss['end'] = end_ms
                    else:
                        ratio = len(ss['text']) / max(1, total_chars)
                        dur = (end_ms - start_ms) * ratio
                        ss['start'] = int(t)
                        ss['end'] = int(t + dur)
                        t += dur
                sentences.extend(sub_sentences)
        else:
            sentences.append({
                'start': start_ms,
                'end':   end_ms,
                'text':  sent_text,
            })

        char_pos = sent_end_in_text

    return sentences


def _force_split_long_sentence(text: str, entries: list[dict], max_chars: int = 100) -> list[dict]:
    """
    对超长句子，按逗号/分号强制拆分。
    如果没有合适的标点，按字数在空格处拆。
    """
    # 在逗号、分号处拆分
    parts = re.split(r'([,;])\s*', text)

    # 重新组合：把标点附加到前一个片段
    fragments = []
    current = ''
    for part in parts:
        if part in (',', ';'):
            current += part
            fragments.append(current.strip())
            current = ''
        else:
            current += part
    if current.strip():
        fragments.append(current.strip())

    # 如果某个片段仍然太长，在空格处强制拆
    final_fragments = []
    for frag in fragments:
        if len(frag) > max_chars:
            words = frag.split()
            chunk = ''
            for w in words:
                if chunk and len(chunk) + len(w) + 1 > max_chars:
                    final_fragments.append(chunk.strip())
                    chunk = w
                else:
                    chunk = (chunk + ' ' + w).strip() if chunk else w
            if chunk.strip():
                final_fragments.append(chunk.strip())
        else:
            final_fragments.append(frag)

    # 映射回时间戳（按比例分配 entries）
    if not entries:
        return [{'start': 0, 'end': 0, 'text': text}]

    total_chars = sum(len(f) for f in final_fragments)
    if total_chars == 0:
        return [{'start': entries[0]['start'], 'end': entries[-1]['end'], 'text': text}]

    results = []
    entry_idx = 0
    for fi, frag in enumerate(final_fragments):
        if not frag:
            continue
        # 按字符比例估计对应的 entry 范围
        frag_ratio = len(frag) / total_chars
        entry_count = max(1, int(frag_ratio * len(entries)))
        entry_end = min(entry_idx + entry_count - 1, len(entries) - 1)

        # 最后一个片段一定覆盖到最后
        if fi == len(fragments) - 1:
            entry_end = len(entries) - 1

        if entry_idx >= len(entries):
            entry_idx = len(entries) - 1

        results.append({
            'start': entries[entry_idx]['start'],
            'end':   entries[entry_end]['end'],
            'text':  frag,
        })
        entry_idx = entry_end + 1

    # 确保最后一个片段覆盖到最后一个 entry
    if results and entry_idx < len(entries):
        results[-1]['end'] = entries[-1]['end']

    return results


def merge_entries(entries: list[dict], max_chars: int = 100, ideal_chars: int = 75) -> list[dict]:
    """
    主合并逻辑：先按语音停顿分组，再用 nltk 在组内按句子断句。
    """
    if not entries:
        return []

    groups = group_by_gap(entries)
    print(f"  语音段分组: {len(groups)} 组（原始 {len(entries)} 条）")

    all_sentences = []
    for group in groups:
        sentences = split_group_into_sentences(group, max_chars, ideal_chars)
        all_sentences.extend(sentences)

    return all_sentences


def fix_overlaps(sentences: list[dict], gap_ms: int = 100) -> list[dict]:
    """
    后处理（单遍正向扫描）：确保时间戳单调递增，每句至少 500ms。
    用单遍扫描避免多遍互相破坏保证。
    """
    MIN_DUR = 500

    for i in range(len(sentences)):
        # 1) start 不能早于上一句 end + gap
        if i > 0:
            min_start = sentences[i - 1]['end'] + gap_ms
            if sentences[i]['start'] < min_start:
                sentences[i]['start'] = min_start

        # 2) end 至少在 start 之后 MIN_DUR
        if sentences[i]['end'] - sentences[i]['start'] < MIN_DUR:
            sentences[i]['end'] = sentences[i]['start'] + MIN_DUR

    return sentences


def build_srt(sentences: list[dict]) -> str:
    blocks = []
    for i, s in enumerate(sentences, 1):
        ts = f"{ms_to_srt_ts(s['start'])} --> {ms_to_srt_ts(s['end'])}"
        blocks.append(f"{i}\n{ts}\n{s['text']}")
    return '\n\n'.join(blocks) + '\n'


def main():
    if len(sys.argv) < 2:
        print("用法: python3 merge_srt.py <input.srt> [output.srt] [video_width]", file=sys.stderr)
        sys.exit(1)

    in_path  = Path(sys.argv[1])
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else in_path
    video_width = int(sys.argv[3]) if len(sys.argv) > 3 else 1920

    if not in_path.exists():
        print(f"文件不存在: {in_path}", file=sys.stderr)
        sys.exit(1)

    # 根据视频宽度设置字符限制
    global MAX_SENTENCE_CHARS
    max_chars, ideal_chars = get_char_limits(video_width)
    MAX_SENTENCE_CHARS = max_chars
    print(f"视频宽度: {video_width}px → 每句最多 {max_chars} 字符，理想 {ideal_chars} 字符")

    raw = in_path.read_text(encoding='utf-8')
    entries = parse_srt(raw)
    print(f"原始字幕: {len(entries)} 条")

    sentences = merge_entries(entries, max_chars, ideal_chars)
    sentences = fix_overlaps(sentences)
    print(f"合并后:   {len(sentences)} 条句子")

    out_path.write_text(build_srt(sentences), encoding='utf-8')
    print(f"✅ 已写入: {out_path}")


if __name__ == '__main__':
    main()
