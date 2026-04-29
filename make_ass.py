#!/usr/bin/env python3
"""
make_ass.py — 英文 SRT + 中文 SRT → 双语 ASS 字幕
用法: python3 make_ass.py <en.srt> <zh.srt> <output.ass>

样式：
  英文：Arial 26px，白色，黑色描边，位置偏下（上方）
  中文：PingFang SC 30px，黄色，黑色描边，最下方
"""

import sys
import re
from pathlib import Path


# ── SRT 解析 ──────────────────────────────────────────────────────────────────

def srt_time_to_ass(ts: str) -> str:
    """00:01:23,456  →  0:01:23.46"""
    ts = ts.replace(',', '.')
    h, m, rest = ts.split(':')
    s, ms = rest.split('.')
    ms = ms[:2]  # ASS 只用百分秒（2位）
    return f"{int(h)}:{m}:{s}.{ms}"


def ass_time_to_ms(ts: str) -> int:
    """0:01:23.46 → 毫秒"""
    h, m, rest = ts.split(':')
    s, cs = rest.split('.')
    return int(h) * 3600000 + int(m) * 60000 + int(s) * 1000 + int(cs) * 10


def ms_to_ass_time(ms: int) -> str:
    """毫秒 → 0:01:23.46"""
    ms = max(0, ms)
    h = ms // 3600000
    ms %= 3600000
    m = ms // 60000
    ms %= 60000
    s = ms // 1000
    cs = (ms % 1000) // 10
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def fix_overlaps(entries: list[dict], gap_ms: int = 50) -> list[dict]:
    """裁剪每条字幕的结束时间，确保与下一条开始时间之间有 gap_ms 的间隔"""
    for i in range(len(entries) - 1):
        end_ms   = ass_time_to_ms(entries[i]['end'])
        next_ms  = ass_time_to_ms(entries[i + 1]['start'])
        if end_ms > next_ms - gap_ms:
            entries[i]['end'] = ms_to_ass_time(next_ms - gap_ms)
    return entries


def parse_srt(text: str) -> list[dict]:
    blocks = re.split(r'\n\n+', text.strip())
    entries = []
    for block in blocks:
        parts = block.strip().split('\n', 2)
        if len(parts) < 3:
            continue
        idx, ts_line, content = parts[0].strip(), parts[1].strip(), parts[2].strip()
        if not idx.isdigit():
            continue
        m = re.match(r'(.+?)\s*-->\s*(.+)', ts_line)
        if not m:
            continue
        start = srt_time_to_ass(m.group(1).strip())
        end   = srt_time_to_ass(m.group(2).strip())
        # 去掉 HTML 标签（<i>, <b> 等），ASS 有自己的标签
        text_clean = re.sub(r'<[^>]+>', '', content).strip()
        entries.append({
            'index': idx,
            'start': start,
            'end':   end,
            'text':  text_clean,
        })
    return entries


# ── ASS 生成 ──────────────────────────────────────────────────────────────────

def build_ass_header(width: int, height: int) -> str:
    """根据视频分辨率生成 ASS 头，自动适配竖屏/横屏"""
    is_vertical = height > width
    if is_vertical:
        # 竖屏：中文在下，英文在上
        en_size, zh_size = 26, 30
        en_margin, zh_margin = 100, 50
    else:
        # 横屏：中文在下，英文在上
        en_size, zh_size = 28, 32
        en_margin, zh_margin = 65, 20

    return f"""\
[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
; 颜色格式: &HAABBGGRR (AA=00 全不透明)
; 白色: &H00FFFFFF  黄色: &H0000FFFF  黑色: &H00000000
Style: English,Arial,{en_size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,0,2,20,20,{en_margin},1
Style: Chinese,PingFang SC,{zh_size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,2,0,2,20,20,{zh_margin},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def ass_text(raw: str) -> str:
    """把多行字幕合并为单行，换行用 \\N"""
    return raw.replace('\n', r'\N')


def build_ass(en_entries: list[dict], zh_entries: list[dict], width: int = 1920, height: int = 1080) -> str:
    # 用 index 作为 key 对齐中英文
    zh_map = {e['index']: e for e in zh_entries}

    lines = [build_ass_header(width, height)]
    for en in en_entries:
        zh = zh_map.get(en['index'])
        en_line = (
            f"Dialogue: 0,{en['start']},{en['end']},English,,0,0,0,,{ass_text(en['text'])}"
        )
        lines.append(en_line)
        if zh and zh['text'].strip():
            zh_line = (
                f"Dialogue: 0,{en['start']},{en['end']},Chinese,,0,0,0,,{ass_text(zh['text'])}"
            )
            lines.append(zh_line)

    return '\n'.join(lines) + '\n'


# ── 入口 ──────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 4:
        print("用法: python3 make_ass.py <en.srt> <zh.srt> <output.ass> [width height]", file=sys.stderr)
        sys.exit(1)

    en_path  = Path(sys.argv[1])
    zh_path  = Path(sys.argv[2])
    out_path = Path(sys.argv[3])
    width    = int(sys.argv[4]) if len(sys.argv) > 4 else 1920
    height   = int(sys.argv[5]) if len(sys.argv) > 5 else 1080

    for p in (en_path, zh_path):
        if not p.exists():
            print(f"文件不存在: {p}", file=sys.stderr)
            sys.exit(1)

    en_entries = parse_srt(en_path.read_text(encoding='utf-8'))
    zh_entries = parse_srt(zh_path.read_text(encoding='utf-8'))

    en_entries = fix_overlaps(en_entries)
    zh_entries = fix_overlaps(zh_entries)

    print(f"英文字幕: {len(en_entries)} 条")
    print(f"中文字幕: {len(zh_entries)} 条")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(build_ass(en_entries, zh_entries, width, height), encoding='utf-8-sig')
    print(f"✅ 双语 ASS 已写入: {out_path}")


if __name__ == '__main__':
    main()
