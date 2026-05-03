#!/usr/bin/env python3
"""
merge_srt_v2.py — 用 Whisper 生成高质量字幕（文字+时间戳都来自 Whisper）

用法:
    python3 merge_srt_v2.py <video.mp4> <output.srt> [video_width]
"""

import sys
import os
import re
from pathlib import Path

import nltk
try:
    nltk.data.find('tokenizers/punkt_tab')
except LookupError:
    nltk.download('punkt_tab', quiet=True)
from nltk.tokenize import sent_tokenize


def whisper_transcribe(video_path: str, model_size: str = "base") -> list[dict]:
    """用 faster-whisper 获取词级时间戳"""
    from faster_whisper import WhisperModel

    audio_path = "/tmp/_whisper_audio.wav"
    os.system(f'ffmpeg -y -i "{video_path}" -vn -acodec pcm_s16le -ar 16000 -ac 1 "{audio_path}" 2>/dev/null')

    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, info = model.transcribe(audio_path, language="en", word_timestamps=True)

    words = []
    for seg in segments:
        for w in seg.words:
            words.append({
                'word': w.word.strip(),
                'start': int(w.start * 1000),
                'end': int(w.end * 1000),
            })
    return words


def get_char_limits(width: int) -> tuple[int, int]:
    max_c = max(20, int(width / 24))
    ideal_c = max(15, int(max_c * 0.75))
    return max_c, ideal_c


def ms_to_srt_ts(ms: int) -> str:
    ms = max(0, ms)
    h = ms // 3600000; ms %= 3600000
    m = ms // 60000;   ms %= 60000
    s = ms // 1000;    rem = ms % 1000
    return f"{h:02d}:{m:02d}:{s:02d},{rem:03d}"


def build_srt(sentences: list[dict]) -> str:
    blocks = []
    for i, s in enumerate(sentences, 1):
        ts = f"{ms_to_srt_ts(s['start'])} --> {ms_to_srt_ts(s['end'])}"
        blocks.append(f"{i}\n{ts}\n{s['text']}")
    return '\n\n'.join(blocks) + '\n'


def main():
    if len(sys.argv) < 3:
        print("用法: python3 merge_srt_v2.py <video.mp4> <output.srt> [video_width]")
        sys.exit(1)

    video_path = Path(sys.argv[1])
    out_path = Path(sys.argv[2])
    video_width = int(sys.argv[3]) if len(sys.argv) > 3 else 1920

    max_chars, ideal_chars = get_char_limits(video_width)
    print(f"视频宽度: {video_width}px → 每句最多 {max_chars} 字符")

    # 1. Whisper 转录
    print("🎤 Whisper 转录中...")
    words = whisper_transcribe(str(video_path), "base")
    print(f"   识别到 {len(words)} 个词")

    # 2. 拼接全文，用 nltk 断句
    full_text = ' '.join(w['word'] for w in words)
    raw_sentences = sent_tokenize(full_text)
    print(f"   断句: {len(raw_sentences)} 句")

    # 3. 为每个句子找到对应的词时间范围
    sentences = []
    word_idx = 0

    for sent_text in raw_sentences:
        sent_text = sent_text.strip()
        if not sent_text:
            continue

        sent_words = sent_text.split()
        # 在 words[word_idx:] 中找这组词
        # 用简单的滑动窗口匹配
        best_start = word_idx
        best_count = 0

        for offset in range(0, 5):
            start = word_idx + offset
            if start >= len(words):
                break
            count = 0
            for j, sw in enumerate(sent_words):
                if start + j >= len(words):
                    break
                if sw.lower().strip('.,!?;:') == words[start + j]['word'].lower().strip('.,!?;:'):
                    count += 1
            if count > best_count:
                best_count = count
                best_start = start

        # 取匹配到的词的时间范围
        matched_count = min(len(sent_words), len(words) - best_start)
        if matched_count > 0:
            start_ms = words[best_start]['start']
            end_ms = words[best_start + matched_count - 1]['end']
            word_idx = best_start + matched_count
        else:
            start_ms = sentences[-1]['end'] if sentences else 0
            end_ms = start_ms + 1000

        # 如果超长，拆分
        if len(sent_text) > max_chars:
            # 按词数比例拆分
            sub_texts = []
            words_in_sent = sent_text.split()
            chunk = ''
            for w in words_in_sent:
                if chunk and len(chunk) + len(w) + 1 > max_chars:
                    sub_texts.append(chunk.strip())
                    chunk = w
                else:
                    chunk = (chunk + ' ' + w).strip() if chunk else w
            if chunk.strip():
                sub_texts.append(chunk.strip())

            # 按比例分配时间
            total_chars = sum(len(t) for t in sub_texts)
            t = start_ms
            for si, st in enumerate(sub_texts):
                ratio = len(st) / max(1, total_chars)
                dur = max(500, int((end_ms - start_ms) * ratio))
                if si == len(sub_texts) - 1:
                    sentences.append({'start': int(t), 'end': end_ms, 'text': st})
                else:
                    sentences.append({'start': int(t), 'end': int(t + dur), 'text': st})
                    t += dur
        else:
            if end_ms - start_ms < 500:
                end_ms = start_ms + 500
            sentences.append({'start': start_ms, 'end': end_ms, 'text': sent_text})

    # 4. 后处理：确保单调递增
    for i in range(1, len(sentences)):
        if sentences[i]['start'] < sentences[i-1]['end'] + 100:
            sentences[i]['start'] = sentences[i-1]['end'] + 100
        if sentences[i]['end'] - sentences[i]['start'] < 500:
            sentences[i]['end'] = sentences[i]['start'] + 500

    # 5. 输出
    out_path.write_text(build_srt(sentences), encoding='utf-8')
    print(f"✅ 已写入 {len(sentences)} 条: {out_path}")


if __name__ == '__main__':
    main()
