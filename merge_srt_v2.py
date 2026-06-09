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

from sentence_splitter import sent_tokenize


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


def _normalize_token(token: str) -> str:
    return token.lower().strip('.,!?;:"\'()[]{}')


def split_word_indices_by_chars(words: list[str], max_chars: int) -> list[tuple[int, int]]:
    """Split a word list into max_chars chunks, returning half-open word ranges."""
    if not words:
        return []

    chunks: list[tuple[int, int]] = []
    start = 0
    current = ""
    for i, word in enumerate(words):
        candidate = f"{current} {word}".strip() if current else word
        if current and len(candidate) > max_chars:
            chunks.append((start, i))
            start = i
            current = word
        else:
            current = candidate

    chunks.append((start, len(words)))
    return chunks


def fix_sentence_timings(sentences: list[dict], gap_ms: int = 50, min_duration_ms: int = 350) -> list[dict]:
    """
    Keep sentence starts anchored to speech. When two captions overlap, trim the
    previous end before moving the next start, because pushing starts later is
    what makes subtitles feel out of sync.
    """
    if not sentences:
        return sentences

    for i, sentence in enumerate(sentences):
        if sentence['end'] - sentence['start'] < min_duration_ms:
            sentence['end'] = sentence['start'] + min_duration_ms

        if i == 0:
            continue

        prev = sentences[i - 1]
        target_prev_end = sentence['start'] - gap_ms
        if prev['end'] > target_prev_end:
            prev['end'] = max(prev['start'] + min_duration_ms, target_prev_end)

        if prev['end'] > sentence['start']:
            sentence['start'] = prev['end']
            if sentence['end'] - sentence['start'] < min_duration_ms:
                sentence['end'] = sentence['start'] + min_duration_ms

    return sentences


def build_sentences_from_words(words: list[dict], video_width: int) -> list[dict]:
    max_chars, _ideal_chars = get_char_limits(video_width)

    full_text = ' '.join(w['word'] for w in words)
    raw_sentences = sent_tokenize(full_text)
    print(f"   断句: {len(raw_sentences)} 句")

    sentences = []
    word_idx = 0

    for sent_text in raw_sentences:
        sent_text = sent_text.strip()
        if not sent_text:
            continue

        sent_words = sent_text.split()
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
                if _normalize_token(sw) == _normalize_token(words[start + j]['word']):
                    count += 1
            if count > best_count:
                best_count = count
                best_start = start

        matched_count = min(len(sent_words), len(words) - best_start)
        if matched_count <= 0:
            start_ms = sentences[-1]['end'] if sentences else 0
            sentences.append({'start': start_ms, 'end': start_ms + 1000, 'text': sent_text})
            continue

        matched_words = words[best_start:best_start + matched_count]
        word_idx = best_start + matched_count

        if len(sent_text) > max_chars:
            for chunk_start, chunk_end in split_word_indices_by_chars(sent_words, max_chars):
                if chunk_start >= matched_count:
                    break
                actual_end = min(chunk_end, matched_count)
                chunk_words = sent_words[chunk_start:chunk_end]
                chunk_timed_words = matched_words[chunk_start:actual_end]
                if not chunk_words or not chunk_timed_words:
                    continue
                sentences.append({
                    'start': chunk_timed_words[0]['start'],
                    'end': chunk_timed_words[-1]['end'],
                    'text': ' '.join(chunk_words),
                })
        else:
            sentences.append({
                'start': matched_words[0]['start'],
                'end': matched_words[-1]['end'],
                'text': sent_text,
            })

    return fix_sentence_timings(sentences)


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

    # 2. 断句，并直接用词级时间戳给每条字幕定时
    sentences = build_sentences_from_words(words, video_width)

    # 3. 输出
    out_path.write_text(build_srt(sentences), encoding='utf-8')
    print(f"✅ 已写入 {len(sentences)} 条: {out_path}")


if __name__ == '__main__':
    main()
