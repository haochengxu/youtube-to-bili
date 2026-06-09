#!/usr/bin/env python3
"""
resplit.py — 短视频专用：把"整句中文"按词级子片段时间回填，避免整句提前显示。

输入：
  merged.en.srt   句子级英文（合并后，用于翻译）
  merged.zh.srt   句子级中文（翻译产物，与 en 同 index）
  subsegs.json    每条合并句的子片段列表 [[{start,end,text}, ...], ...]（毫秒）
输出（覆盖写）：
  out.en.srt / out.zh.srt   细粒度：每个子片段一条，中文按英文字数比例切分到各片段

用法: python3 resplit.py <merged.en.srt> <merged.zh.srt> <subsegs.json> <out.en.srt> <out.zh.srt>
"""
import sys
import json
import re
from pathlib import Path


def parse_srt(text: str) -> list[dict]:
    out = []
    for block in re.split(r'\n\n+', text.strip()):
        parts = block.strip().split('\n', 2)
        if len(parts) >= 3 and parts[0].strip().isdigit():
            out.append({'index': parts[0].strip(), 'ts': parts[1].strip(),
                        'text': parts[2].strip()})
    return out


def ms_to_ts(ms: int) -> str:
    ms = max(0, int(ms))
    h = ms // 3600000; ms %= 3600000
    m = ms // 60000;   ms %= 60000
    s = ms // 1000;    rem = ms % 1000
    return f"{h:02d}:{m:02d}:{s:02d},{rem:03d}"


def split_by_weights(text: str, weights: list[int]) -> list[str]:
    """按权重把 text 切成 len(weights) 段（中文任意处可切）。"""
    text = text.strip()
    n = len(text)
    total = sum(weights) or 1
    parts, start, cum = [], 0, 0
    for i, w in enumerate(weights):
        cum += w
        end = n if i == len(weights) - 1 else max(start, min(n, round(n * cum / total)))
        parts.append(text[start:end])
        start = end
    return parts


def main():
    if len(sys.argv) < 6:
        print("用法: resplit.py <merged.en.srt> <merged.zh.srt> <subsegs.json> <out.en.srt> <out.zh.srt>",
              file=sys.stderr)
        sys.exit(1)
    en_merged = parse_srt(Path(sys.argv[1]).read_text(encoding='utf-8'))
    zh_merged = {e['index']: e['text'] for e in parse_srt(Path(sys.argv[2]).read_text(encoding='utf-8'))}
    subsegs = json.loads(Path(sys.argv[3]).read_text(encoding='utf-8'))

    fine_en, fine_zh = [], []
    idx = 1
    for i, subs in enumerate(subsegs):
        zh_text = zh_merged.get(str(i + 1), '')
        weights = [max(1, len(s['text'])) for s in subs]
        zh_parts = split_by_weights(zh_text, weights) if zh_text else [''] * len(subs)
        for sub, zh_part in zip(subs, zh_parts):
            ts = f"{ms_to_ts(sub['start'])} --> {ms_to_ts(sub['end'])}"
            fine_en.append({'index': str(idx), 'ts': ts, 'text': sub['text']})
            fine_zh.append({'index': str(idx), 'ts': ts, 'text': zh_part})
            idx += 1

    def dump(entries):
        return '\n\n'.join(f"{e['index']}\n{e['ts']}\n{e['text']}" for e in entries) + '\n'

    Path(sys.argv[4]).write_text(dump(fine_en), encoding='utf-8')
    Path(sys.argv[5]).write_text(dump(fine_zh), encoding='utf-8')
    print(f"✅ 词级回填：{len(en_merged)} 句 → {len(fine_en)} 条细片段")


if __name__ == '__main__':
    main()
