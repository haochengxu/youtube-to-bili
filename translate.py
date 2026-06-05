#!/usr/bin/env python3
"""
translate.py — 英文 SRT → 中文 SRT
用法: python3 translate.py <input.en.srt>
输出: 同目录下 <input.zh.srt>
依赖: TRANSLATOR=codex|copilot|hermes（默认 codex）
"""

import os
import sys
import re
from pathlib import Path
from translator_cli import TranslatorError, available_backends, run_llm

BATCH_SIZE = int(os.environ.get("TRANSLATE_BATCH_SIZE", "50"))  # 每批翻译的字幕条数


def parse_srt(text: str) -> list[dict]:
    """解析 SRT 文件，返回 [{index, timestamp, lines}, ...]"""
    blocks = re.split(r'\n\n+', text.strip())
    entries = []
    for block in blocks:
        parts = block.strip().split('\n', 2)
        if len(parts) < 3:
            continue
        idx, ts, content = parts[0].strip(), parts[1].strip(), parts[2].strip()
        if not idx.isdigit():
            continue
        entries.append({
            'index': idx,
            'timestamp': ts,
            'lines': content,
        })
    return entries


def build_srt(entries: list[dict]) -> str:
    blocks = []
    for e in entries:
        blocks.append(f"{e['index']}\n{e['timestamp']}\n{e['lines']}")
    return '\n\n'.join(blocks) + '\n'


def translate_batch(entries: list[dict]) -> list[str]:
    """调用配置的翻译后端翻译一批字幕，返回对应的中文文本列表"""
    numbered = '\n'.join(
        f"[{i+1}] {e['lines'].replace(chr(10), ' ')}"
        for i, e in enumerate(entries)
    )
    prompt = (
        "你是专业视频字幕翻译，将下列英文字幕翻译成简体中文。\n"
        "规则：\n"
        "1. 保持编号格式 [N] 不变\n"
        "2. 每条字幕翻译成一行，不换行\n"
        "3. 只输出翻译结果，不加任何解释或额外内容\n"
        "4. 翻译要口语化、自然流畅，符合中文表达习惯\n"
        "5. 人名、品牌名、专有技术名词保留英文原文\n"
        "6. 字幕之间有上下文关联，请保持语义连贯\n"
        "7. 短句不要拆分，保持与原文节奏一致\n\n"
        f"{numbered}"
    )

    output = run_llm(prompt, timeout=300)
    # 按 [N] 编号回填，而不是按出现顺序——否则模型在中间漏/并一行，
    # 后面全部错位一行（中文配错英文）。用编号对位，缺失的只影响那一条。
    by_num: dict[int, str] = {}
    for line in output.split('\n'):
        line = line.strip()
        m = re.match(r'^\[(\d+)\]\s*(.*)', line)
        if m:
            by_num[int(m.group(1))] = m.group(2).strip()

    translated = [by_num.get(i + 1, '') for i in range(len(entries))]
    missing = [i + 1 for i, t in enumerate(translated) if not t]
    if missing:
        # 缺失的留空，调用方会回退用英文原文；其余条目编号对得上、不受影响
        print(f"  [警告] 本批 {len(entries)} 条中 {len(missing)} 条未匹配到译文"
              f"（编号 {missing[:10]}{'...' if len(missing) > 10 else ''}），缺失处回退英文")

    return translated


def main():
    if len(sys.argv) < 2:
        print("用法: python3 translate.py <input.en.srt>", file=sys.stderr)
        print(f"翻译后端: TRANSLATOR={available_backends()}（默认 codex）", file=sys.stderr)
        sys.exit(1)

    en_path = Path(sys.argv[1])
    if not en_path.exists():
        print(f"文件不存在: {en_path}", file=sys.stderr)
        sys.exit(1)

    # 输出路径：把最后一个 .en.srt / .srt 换成 .zh.srt
    stem = en_path.name
    if stem.endswith('.en.srt'):
        zh_name = stem[:-7] + '.zh.srt'
    elif stem.endswith('.srt'):
        zh_name = stem[:-4] + '.zh.srt'
    else:
        zh_name = stem + '.zh.srt'
    zh_path = en_path.parent / zh_name

    print(f"读取字幕: {en_path}")
    entries = parse_srt(en_path.read_text(encoding='utf-8'))
    print(f"共 {len(entries)} 条字幕，每批 {BATCH_SIZE} 条")

    zh_entries = []
    for batch_start in range(0, len(entries), BATCH_SIZE):
        batch = entries[batch_start:batch_start + BATCH_SIZE]
        batch_end = batch_start + len(batch)
        print(f"  翻译第 {batch_start+1}–{batch_end} 条...")
        try:
            translated_texts = translate_batch(batch)
        except TranslatorError as exc:
            print(f"翻译失败: {exc}", file=sys.stderr)
            sys.exit(1)
        for orig, zh_text in zip(batch, translated_texts):
            zh_entries.append({
                'index': orig['index'],
                'timestamp': orig['timestamp'],
                'lines': zh_text or orig['lines'],
            })

    zh_path.write_text(build_srt(zh_entries), encoding='utf-8')
    print(f"✅ 中文字幕已写入: {zh_path}")


if __name__ == '__main__':
    main()
