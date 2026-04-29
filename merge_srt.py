#!/usr/bin/env python3
"""
merge_srt.py — 合并 YouTube 滚动式碎片字幕 → 自然句子字幕

YouTube 自动字幕是"滚动式"：每段只有几个词，且时间段互相重叠。
本脚本：
  1. 把所有片段按时间顺序拼成完整文本流（带时间戳锚点）
  2. 按标点（. ? ! ...）断句，同时控制时长和长度
  3. 修复重叠时间轴，确保每句首尾不重叠
  4. 输出干净的非重叠 SRT

用法: python3 merge_srt.py <input.srt> <output.srt>
      python3 merge_srt.py <input.srt>   # 原地覆盖
"""

import sys
import re
from pathlib import Path


# ─── SRT 解析 ─────────────────────────────────────────────────────────────────

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
    # 按开始时间排序
    entries.sort(key=lambda e: e['start'])
    return entries


# ─── 核心：把滚动字幕转为词流（每个词带时间锚点） ────────────────────────────

def build_word_stream(entries: list[dict]) -> list[dict]:
    """
    YouTube 滚动字幕：相邻两段在时间上重叠，文本是续接而不是重复。
    把所有段落的词按时间顺序排列，每个词带一个近似的时间戳。
    每段的词均匀分布在该段的时间窗口内。
    返回: [{'word': str, 'start': ms, 'end': ms}, ...]
    """
    word_stream = []

    for e in entries:
        words = e['text'].split()
        if not words:
            continue
        n = len(words)
        duration = max(e['end'] - e['start'], 100)
        for i, w in enumerate(words):
            ws = e['start'] + int(duration * i / n)
            we = e['start'] + int(duration * (i + 1) / n)
            word_stream.append({'word': w, 'start': ws, 'end': we})

    # 去重：相邻完全相同的词（有时 YouTube 会重复）
    deduped = []
    for w in word_stream:
        if deduped and deduped[-1]['word'].lower() == w['word'].lower():
            # 如果时间非常接近，认为是重复
            if w['start'] - deduped[-1]['end'] < 500:
                continue
        deduped.append(w)

    return deduped


# ─── 断句：按标点 + 时长 + 长度 ──────────────────────────────────────────────

SENTENCE_END = re.compile(r'[.?!…]+$')
MAX_DURATION_MS = 7000   # 每句最多 7 秒
MAX_CHARS = 100          # 每句最多字符数
MIN_WORDS = 4            # 每句至少 4 个词才考虑断句


def segment_into_sentences(word_stream: list[dict]) -> list[dict]:
    """
    把词流分割成句子，返回 [{start, end, text}, ...]
    """
    if not word_stream:
        return []

    sentences = []
    buf: list[dict] = []

    def flush_buf():
        if not buf:
            return
        text = ' '.join(w['word'] for w in buf)
        sentences.append({
            'start': buf[0]['start'],
            'end':   buf[-1]['end'],
            'text':  text,
        })
        buf.clear()

    for w in word_stream:
        buf.append(w)
        duration = buf[-1]['end'] - buf[0]['start']
        text_so_far = ' '.join(x['word'] for x in buf)

        # 超长强制断句
        if duration >= MAX_DURATION_MS or len(text_so_far) >= MAX_CHARS:
            flush_buf()
            continue

        # 句末标点断句（至少积累够 MIN_WORDS 个词）
        if len(buf) >= MIN_WORDS and SENTENCE_END.search(w['word']):
            flush_buf()

    flush_buf()
    return sentences


def fix_overlaps(sentences: list[dict], gap_ms: int = 50) -> list[dict]:
    """确保相邻句子时间不重叠"""
    for i in range(len(sentences) - 1):
        if sentences[i]['end'] > sentences[i+1]['start'] - gap_ms:
            sentences[i]['end'] = sentences[i+1]['start'] - gap_ms
    return sentences


def renumber_and_build_srt(sentences: list[dict]) -> str:
    blocks = []
    for i, s in enumerate(sentences, 1):
        ts = f"{ms_to_srt_ts(s['start'])} --> {ms_to_srt_ts(s['end'])}"
        blocks.append(f"{i}\n{ts}\n{s['text']}")
    return '\n\n'.join(blocks) + '\n'


# ─── 主流程 ───────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("用法: python3 merge_srt.py <input.srt> [output.srt]", file=sys.stderr)
        sys.exit(1)

    in_path  = Path(sys.argv[1])
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else in_path

    if not in_path.exists():
        print(f"文件不存在: {in_path}", file=sys.stderr)
        sys.exit(1)

    raw = in_path.read_text(encoding='utf-8')
    entries = parse_srt(raw)
    print(f"原始字幕: {len(entries)} 条")

    word_stream = build_word_stream(entries)
    print(f"词流:     {len(word_stream)} 个词")

    sentences = segment_into_sentences(word_stream)
    sentences = fix_overlaps(sentences)
    print(f"合并后:   {len(sentences)} 条句子")

    out_path.write_text(renumber_and_build_srt(sentences), encoding='utf-8')
    print(f"✅ 已写入: {out_path}")


if __name__ == '__main__':
    main()
