#!/usr/bin/env python3
"""
make_ass.py — 英文 SRT + 中文 SRT → 双语 ASS 字幕
用法: python3 make_ass.py <en.srt> <zh.srt> <output.ass>

样式：
  英文：Arial 26px，白色，黑色描边，位置偏下（上方）
  中文：Heiti SC 30px，黄色，黑色描边，最下方
"""

import argparse
import sys
import re
import os
from pathlib import Path

from subtitle_display import decide_show_english


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
    """根据视频分辨率生成 ASS 头，自动适配竖屏/横屏，字号按宽度缩放"""
    is_vertical = height > width
    if is_vertical:
        # 竖屏：基准 1080px 宽
        base_en, base_zh = 34, 50
        # 竖屏默认只留中文（见 decide_show_english）。中文上移进"源英文与底边之间"
        # 的空白带、字号调大、长句自动换行；源字幕在画面中部，不会被遮挡。
        # 可用 SUB_ZH_SIZE / SUB_ZH_MARGIN 微调而不改码。
        en_margin, zh_margin = 110, 150
    else:
        # 横屏：基准 1920px 宽
        base_en, base_zh = 44, 52
        en_margin, zh_margin = 120, 24
    # 按宽度缩放字号，基准宽度取 1080（竖屏）或 1920（横屏）
    ref_w = 1080 if is_vertical else 1920
    scale = max(0.6, min(1.2, width / ref_w))
    en_size = max(18, int(base_en * scale))
    zh_size = max(20, int(base_zh * scale))
    # 竖屏中文字号/位置可用环境变量微调（不改码）
    if is_vertical:
        zh_size = int(os.environ.get("SUB_ZH_SIZE", zh_size))
        zh_margin = int(os.environ.get("SUB_ZH_MARGIN", zh_margin))

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
; Alignment: 2=底部居中（英文和中文都在底部，靠 MarginV 区分上下）
Style: English,Arial,{en_size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,0,2,20,20,{en_margin},1
Style: Chinese,Heiti SC,{zh_size},&H0000FFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,2,0,2,20,20,{zh_margin},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def ass_text(raw: str) -> str:
    """把多行字幕合并为单行，换行用 \\N"""
    return raw.replace('\n', r'\N')


def wrap_cjk(text: str, max_chars: int) -> str:
    """按字数给中文强制折行（插入 \\N）。
    libass 对无空格的中文不会自动换行，长句会两头溢出被裁，必须手动折。
    优先在标点后断，否则到字数上限硬断。"""
    text = text.strip()
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    breakable = "，。！？、；：,.!?;: ”’）)】」"
    lines, line = [], ""
    for ch in text:
        line += ch
        if len(line) >= max_chars and ch in breakable:
            lines.append(line)
            line = ""
        elif len(line) >= max_chars + 4:  # 迟迟没标点，硬断
            lines.append(line)
            line = ""
    if line:
        lines.append(line)
    return r"\N".join(lines)


def should_show_english(width: int, height: int, requested: str | None = None, burned_subtitles: str | None = None) -> bool:
    return decide_show_english(
        width,
        height,
        requested=requested or os.environ.get('SHOW_ENGLISH', 'auto'),
        burned_subtitles=burned_subtitles or os.environ.get('BURNED_SUBTITLES', 'unknown'),
    )


def build_ass(
    en_entries: list[dict],
    zh_entries: list[dict],
    width: int = 1920,
    height: int = 1080,
    show_english_request: str | None = None,
    burned_subtitles: str | None = None,
) -> str:
    # 用 index 作为 key 对齐中英文
    zh_map = {e['index']: e for e in zh_entries}
    show_english = should_show_english(width, height, show_english_request, burned_subtitles)

    # 竖屏：估算中文每行最多多少字，主动给长句折行
    # （libass 对无空格的中文不会自动换行，长句会两头溢出被裁）
    zh_wrap = 0
    if height > width:
        _scale = max(0.6, min(1.2, width / 1080))
        _zh_size = int(os.environ.get("SUB_ZH_SIZE", max(20, int(50 * _scale))))
        zh_wrap = max(8, (width - 40) // _zh_size - 1)  # 减 MarginL/R 再留 1 字余量

    lines = [build_ass_header(width, height)]
    for en in en_entries:
        # 跳过时间无效的行（start >= end）
        en_start_ms = ass_time_to_ms(en['start'])
        en_end_ms   = ass_time_to_ms(en['end'])
        if en_start_ms >= en_end_ms:
            continue
        zh = zh_map.get(en['index'])
        if show_english:
            en_line = (
                f"Dialogue: 0,{en['start']},{en['end']},English,,0,0,0,,{ass_text(en['text'])}"
            )
            lines.append(en_line)
        if zh and zh['text'].strip():
            zh_txt = wrap_cjk(zh['text'], zh_wrap) if zh_wrap else ass_text(zh['text'])
            zh_line = (
                f"Dialogue: 0,{en['start']},{en['end']},Chinese,,0,0,0,,{zh_txt}"
            )
            lines.append(zh_line)

    return '\n'.join(lines) + '\n'


# ── 入口 ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Generate bilingual ASS subtitles')
    parser.add_argument('en_srt')
    parser.add_argument('zh_srt')
    parser.add_argument('output_ass')
    parser.add_argument('width', nargs='?', type=int, default=1920)
    parser.add_argument('height', nargs='?', type=int, default=1080)
    parser.add_argument('--show-english', default=None)
    parser.add_argument('--burned-subtitles', default=None)
    args = parser.parse_args()

    en_path  = Path(args.en_srt)
    zh_path  = Path(args.zh_srt)
    out_path = Path(args.output_ass)
    width    = args.width
    height   = args.height

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
    out_path.write_text(
        build_ass(
            en_entries,
            zh_entries,
            width,
            height,
            show_english_request=args.show_english,
            burned_subtitles=args.burned_subtitles,
        ),
        encoding='utf-8-sig',
    )
    print(f"✅ 双语 ASS 已写入: {out_path}")


if __name__ == '__main__':
    main()
