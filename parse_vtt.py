#!/usr/bin/env python3
"""
parse_vtt.py — 解析 YouTube VTT 字幕（含逐词时间戳）→ 断句 SRT

YouTube VTT 格式示例：
  00:00:01.234 --> 00:00:03.456 align:start position:0%
  <00:00:01.234><c>hey</c> <00:00:01.800><c>guys</c> <00:00:02.300><c>welcome</c>

本脚本提取逐词精确时间戳，按标点+长度断句，输出对齐语音的 SRT。

用法: python3 parse_vtt.py <input.vtt> <output.srt>
"""

import sys
import re
import html
from pathlib import Path


# ── VTT 解析 ──────────────────────────────────────────────────────────────────

def vtt_ts_to_ms(ts: str) -> int:
    """00:01:23.456 或 01:23.456 → ms"""
    ts = ts.strip()
    parts = ts.split(':')
    if len(parts) == 3:
        h, m, s = parts
    else:
        h = '0'
        m, s = parts
    s, ms_str = s.split('.')
    ms_str = ms_str.ljust(3, '0')[:3]
    return int(h) * 3600000 + int(m) * 60000 + int(s) * 1000 + int(ms_str)


def ms_to_srt_ts(ms: int) -> str:
    ms = max(0, ms)
    h = ms // 3600000; ms %= 3600000
    m = ms // 60000;   ms %= 60000
    s = ms // 1000;    rem = ms % 1000
    return f"{h:02d}:{m:02d}:{s:02d},{rem:03d}"


def parse_vtt(text: str) -> list[dict]:
    """
    解析 VTT，提取逐词时间戳。
    返回: [{'word': str, 'start': ms, 'end': ms}, ...]
    """
    words = []
    seen_words = set()  # 去重用 (word, start_ms)

    # VTT cue 块：时间行 + 内容行
    cue_pattern = re.compile(
        r'(\d{1,2}:\d{2}:\d{2}\.\d{3}|\d{2}:\d{2}\.\d{3})'  # cue start
        r'\s*-->\s*'
        r'(\d{1,2}:\d{2}:\d{2}\.\d{3}|\d{2}:\d{2}\.\d{3})'  # cue end
        r'[^\n]*\n'                                             # options
        r'(.*?)(?=\n\n|\Z)',                                   # content
        re.DOTALL
    )

    # 逐词时间戳 pattern：<00:00:01.234>
    word_ts_pattern = re.compile(r'<(\d{1,2}:\d{2}:\d{2}\.\d{3}|\d{2}:\d{2}\.\d{3})>')
    # 去掉 <c>...</c> 标签
    tag_pattern = re.compile(r'<[^>]+>')

    def add_words(raw_text: str, start_ms: int, end_ms: int) -> None:
        clean = html.unescape(tag_pattern.sub('', raw_text)).strip()
        for word in clean.split():
            key = (word, start_ms)
            if key not in seen_words:
                seen_words.add(key)
                words.append({'word': word, 'start': start_ms, 'end': end_ms})

    def recent_words_suffix_matches(candidate_words: list[str], window: int = 12) -> bool:
        if not candidate_words or len(words) < len(candidate_words):
            return False
        recent = [w['word'].lower() for w in words[-window:]]
        candidate = [w.lower() for w in candidate_words]
        return recent[-len(candidate):] == candidate

    for m in cue_pattern.finditer(text):
        cue_start_ms = vtt_ts_to_ms(m.group(1))
        cue_end_ms   = vtt_ts_to_ms(m.group(2))
        content      = m.group(3).strip()

        ts_matches = list(word_ts_pattern.finditer(content))

        if not ts_matches:
            # YouTube inserts duplicate "preview" cues without word timestamps.
            # They are usually carry-over display text, not reliable word-level timing.
            # Sometimes the final line contains the next new word without its own
            # timestamp; keep only that tail line so phrases do not lose the last word.
            if not words and cue_end_ms - cue_start_ms > 100:
                add_words(content, cue_start_ms, cue_end_ms)
            elif words:
                content_lines = [
                    html.unescape(tag_pattern.sub('', line)).strip()
                    for line in content.splitlines()
                ]
                content_lines = [line for line in content_lines if line]
                if len(content_lines) >= 2:
                    tail_words = content_lines[-1].split()
                    if tail_words and not recent_words_suffix_matches(tail_words):
                        add_words(content_lines[-1], cue_start_ms, cue_end_ms)
            continue

        # Text before the first timestamp contains a repeated carry-over line plus,
        # sometimes, the first new word. Keep only the last line as the new word.
        first_prefix = content[:ts_matches[0].start()]
        first_prefix = first_prefix.split('\n')[-1]
        clean_prefix = html.unescape(tag_pattern.sub('', first_prefix)).strip()
        add_words(clean_prefix, cue_start_ms, cue_start_ms)

        for i, ts_match in enumerate(ts_matches):
            current_ts = vtt_ts_to_ms(ts_match.group(1))
            text_start = ts_match.end()
            text_end = ts_matches[i + 1].start() if i + 1 < len(ts_matches) else len(content)
            clean = html.unescape(tag_pattern.sub('', content[text_start:text_end])).strip()
            add_words(clean, current_ts, current_ts)

    # 按时间排序
    words.sort(key=lambda x: x['start'])

    # 去重：相邻时间戳相近且词相同的（VTT 重叠块导致）
    deduped = []
    for w in words:
        if deduped and deduped[-1]['word'].lower() == w['word'].lower():
            if w['start'] - deduped[-1]['start'] < 800:  # 800ms 内的重复词去掉
                continue
        deduped.append(w)
    words = deduped

    # 补全 end 时间：每个词的 end = 下一个词的 start
    for i in range(len(words) - 1):
        if words[i]['end'] <= words[i]['start']:
            words[i]['end'] = words[i+1]['start']
    if words:
        if words[-1]['end'] <= words[-1]['start']:
            words[-1]['end'] = words[-1]['start'] + 300

    return words


# ── 断句 ──────────────────────────────────────────────────────────────────────

SENTENCE_END = re.compile(r'[.?!…,，。？！]+$')
MAX_DURATION_MS = 6000   # 每句最多 6 秒
MAX_CHARS = 50            # 每句最多 50 字符
MIN_WORDS = 3             # 至少积累 3 个词才断句


def segment_into_sentences(words: list[dict]) -> list[dict]:
    if not words:
        return []

    sentences = []
    buf: list[dict] = []

    def flush():
        if not buf:
            return
        text = ' '.join(w['word'] for w in buf)
        sentences.append({
            'start': buf[0]['start'],
            'end':   buf[-1]['end'],
            'text':  text,
        })
        buf.clear()

    for w in words:
        buf.append(w)
        duration = buf[-1]['end'] - buf[0]['start']
        text_so_far = ' '.join(x['word'] for x in buf)

        if duration >= MAX_DURATION_MS or len(text_so_far) >= MAX_CHARS:
            flush()
            continue

        if len(buf) >= MIN_WORDS and SENTENCE_END.search(w['word']):
            flush()

    flush()
    return sentences


# ── 孤儿合并 ──────────────────────────────────────────────────────────────────
# 长度硬切会把一句话切断，剩几个词变成"孤儿"甩到下一条。这里把被切断的句子缝回去。
# 关键：合并只延长 end，start 始终保持前一条的 start（=第一个词的时间戳），
#       所以字幕"开始出现"的时刻和声音永远对齐，绝不前移。
MERGE_MAX_CHARS = 78          # 合并后单行上限（Arial 44 在 1880px 可用宽度内仍是单行）
MERGE_MAX_DURATION_MS = 7000  # 合并后总时长上限，防止句尾文字领先音频太久
# 句末标点（注意：逗号不算——逗号结尾是半句，应当继续合并）
SENTENCE_FINISHED = re.compile(r'[.?!…。？！]["”’\')\]]?$')


def merge_orphans(sentences: list[dict]) -> list[dict]:
    if not sentences:
        return sentences
    merged = [dict(sentences[0])]
    for s in sentences[1:]:
        prev = merged[-1]
        combined = f"{prev['text']} {s['text']}"
        prev_unfinished = not SENTENCE_FINISHED.search(prev['text'].strip())
        within_chars = len(combined) <= MERGE_MAX_CHARS
        within_dur = (s['end'] - prev['start']) <= MERGE_MAX_DURATION_MS
        if prev_unfinished and within_chars and within_dur:
            prev['text'] = combined
            prev['end'] = s['end']      # 仅延长结尾；start 不动 → 开头对齐
        else:
            merged.append(dict(s))
    return merged


def fix_overlaps(sentences: list[dict], gap_ms: int = 50) -> list[dict]:
    for i in range(len(sentences) - 1):
        if sentences[i]['end'] > sentences[i+1]['start'] - gap_ms:
            new_end = sentences[i+1]['start'] - gap_ms
            if new_end <= sentences[i]['start']:
                new_end = sentences[i+1]['start']
            if new_end <= sentences[i]['start']:
                new_end = sentences[i]['start'] + 100
            sentences[i]['end'] = new_end
    return sentences


def build_srt(sentences: list[dict]) -> str:
    blocks = []
    for i, s in enumerate(sentences, 1):
        ts = f"{ms_to_srt_ts(s['start'])} --> {ms_to_srt_ts(s['end'])}"
        blocks.append(f"{i}\n{ts}\n{s['text']}")
    return '\n\n'.join(blocks) + '\n'


# ── 主流程 ────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 3:
        print("用法: python3 parse_vtt.py <input.vtt> <output.srt>", file=sys.stderr)
        sys.exit(1)

    in_path  = Path(sys.argv[1])
    out_path = Path(sys.argv[2])

    if not in_path.exists():
        print(f"文件不存在: {in_path}", file=sys.stderr)
        sys.exit(1)

    text  = in_path.read_text(encoding='utf-8')
    words = parse_vtt(text)
    print(f"提取词数: {len(words)}")

    sentences = segment_into_sentences(words)
    before = len(sentences)
    sentences = merge_orphans(sentences)
    sentences = fix_overlaps(sentences)
    print(f"断句结果: {len(sentences)} 条（合并孤儿 {before - len(sentences)} 条）")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(build_srt(sentences), encoding='utf-8')
    print(f"✅ 已写入: {out_path}")


if __name__ == '__main__':
    main()
