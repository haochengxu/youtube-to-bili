#!/usr/bin/env python3
"""
translate.py — 英文 SRT → 中文 SRT
用法: python3 translate.py <input.en.srt>
输出: 同目录下 <input.zh.srt>
依赖: claude CLI（`claude -p` pipe 模式）
"""

import sys
import re
import subprocess
import os
from pathlib import Path

BATCH_SIZE = 80  # 每批翻译的字幕条数


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
    """调用 claude -p 翻译一批字幕，返回对应的中文文本列表"""
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

    result = subprocess.run(
        ['hermes', 'chat', '-q', prompt, '-Q'],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(f"hermes CLI 失败:\n{result.stderr}")

    output = result.stdout.strip()
    translated = []
    for line in output.split('\n'):
        line = line.strip()
        m = re.match(r'^\[(\d+)\]\s*(.*)', line)
        if m:
            translated.append(m.group(2).strip())

    if len(translated) != len(entries):
        # 宽松兜底：按行数对齐，不足补空
        print(f"  [警告] 翻译返回 {len(translated)} 条，期望 {len(entries)} 条，尝试对齐")
        while len(translated) < len(entries):
            translated.append('')

    return translated[:len(entries)]


def main():
    if len(sys.argv) < 2:
        print("用法: python3 translate.py <input.en.srt>", file=sys.stderr)
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
        translated_texts = translate_batch(batch)
        for orig, zh_text in zip(batch, translated_texts):
            zh_entries.append({
                'index': orig['index'],
                'timestamp': orig['timestamp'],
                'lines': zh_text,
            })

    zh_path.write_text(build_srt(zh_entries), encoding='utf-8')
    print(f"✅ 中文字幕已写入: {zh_path}")


if __name__ == '__main__':
    main()
