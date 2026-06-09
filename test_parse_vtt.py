#!/usr/bin/env python3
"""Tests for YouTube VTT parsing edge cases."""

from parse_vtt import fix_overlaps, parse_vtt, segment_into_sentences


def assert_valid_timing(sentences):
    for i, sentence in enumerate(sentences):
        assert sentence["end"] > sentence["start"], f"invalid #{i}: {sentence}"


def test_youtube_duplicate_preview_cues_do_not_make_invalid_srt():
    vtt = """WEBVTT

00:00:02.000 --> 00:00:04.070 align:start position:0%
Always
always<00:00:02.480><c> take</c><00:00:02.639><c> it</c><00:00:02.800><c> into</c><00:00:03.120><c> your</c><00:00:03.360><c> experience</c><00:00:03.840><c> in</c>

00:00:04.070 --> 00:00:04.080 align:start position:0%
always take it into your experience in
 

00:00:04.080 --> 00:00:06.150 align:start position:0%
always take it into your experience in
the<00:00:04.240><c> very</c><00:00:04.400><c> moment</c><00:00:04.720><c> you</c><00:00:04.960><c> hear</c><00:00:05.200><c> it.</c><00:00:05.920><c> Whether</c>
"""
    words = parse_vtt(vtt)
    assert [w["word"] for w in words[:4]] == ["always", "take", "it", "into"]
    sentences = fix_overlaps(segment_into_sentences(words))
    assert_valid_timing(sentences)


def test_youtube_no_timestamp_tail_line_keeps_final_word():
    vtt = """WEBVTT

00:50:53.520 --> 00:50:56.150 align:start position:0%
letting go means.
Did<00:50:53.760><c> it</c><00:50:54.000><c> happen?</c><00:50:54.559><c> Yes.</c><00:50:55.280><c> Is</c><00:50:55.440><c> that</c><00:50:55.680><c> okay</c><00:50:55.920><c> with</c>

00:50:56.150 --> 00:50:56.160 align:start position:0%
Did it happen? Yes. Is that okay with
 

00:50:56.160 --> 00:50:59.109 align:start position:0%
Did it happen? Yes. Is that okay with
you?

00:50:59.109 --> 00:50:59.119 align:start position:0%
you?
"""
    words = parse_vtt(vtt)
    text = " ".join(w["word"] for w in words)
    assert "Is that okay with you?" in text
    assert "Is that okay with Yeah" not in text
    sentences = fix_overlaps(segment_into_sentences(words))
    assert any(sentence["text"] == "Yes. Is that okay with you?" for sentence in sentences)
    assert_valid_timing(sentences)


def run_all_tests():
    tests = [
        test_youtube_duplicate_preview_cues_do_not_make_invalid_srt,
        test_youtube_no_timestamp_tail_line_keeps_final_word,
    ]
    for test in tests:
        test()
        print(f"✅ {test.__name__}")
    print(f"结果: {len(tests)} passed, 0 failed, {len(tests)} total")


if __name__ == "__main__":
    run_all_tests()
