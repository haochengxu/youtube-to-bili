#!/usr/bin/env python3
"""Focused tests for precise Whisper subtitle timing."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from merge_srt_v2 import build_sentences_from_words, fix_sentence_timings


def assert_no_overlap(sentences: list[dict]):
    for i in range(len(sentences) - 1):
        assert sentences[i]['end'] <= sentences[i + 1]['start'], (
            f"overlap: {sentences[i]} then {sentences[i + 1]}"
        )


def test_long_sentence_split_uses_word_timestamps():
    words_text = (
        "This long sentence should split into smaller captions while each new "
        "caption keeps the start time of its first spoken word."
    ).split()
    words = [
        {'word': word, 'start': i * 400, 'end': i * 400 + 280}
        for i, word in enumerate(words_text)
    ]

    sentences = build_sentences_from_words(words, video_width=454)

    assert len(sentences) > 1
    assert sentences[0]['start'] == words[0]['start']
    for sentence in sentences[1:]:
        first_word = sentence['text'].split()[0]
        matching = next(word for word in words if word['word'] == first_word)
        assert sentence['start'] == matching['start'], (
            f"{sentence['text']} starts at {sentence['start']}, "
            f"expected {matching['start']}"
        )
    assert_no_overlap(sentences)


def test_overlap_fix_trims_previous_before_delaying_next():
    sentences = [
        {'start': 1000, 'end': 2500, 'text': 'First caption.'},
        {'start': 2200, 'end': 3200, 'text': 'Second caption.'},
    ]

    fixed = fix_sentence_timings(sentences)

    assert fixed[1]['start'] == 2200
    assert fixed[0]['end'] <= fixed[1]['start']
    assert fixed[0]['end'] >= fixed[0]['start'] + 350


def run_all_tests():
    tests = [
        test_long_sentence_split_uses_word_timestamps,
        test_overlap_fix_trims_previous_before_delaying_next,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            print(f"✅ {test.__name__}")
            passed += 1
        except AssertionError as exc:
            print(f"❌ {test.__name__}: {exc}")
            failed += 1

    print(f"结果: {passed} passed, {failed} failed, {passed + failed} total")
    if failed:
        sys.exit(1)


if __name__ == '__main__':
    run_all_tests()
