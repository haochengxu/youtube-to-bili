#!/usr/bin/env python3
"""Focused tests for generated ASS subtitle styles."""

import re

from make_ass import build_ass_header


def style_font_size(header: str, style_name: str) -> int:
    match = re.search(rf"^Style: {style_name},[^,]+,(\d+),", header, re.MULTILINE)
    assert match, f"missing {style_name} style"
    return int(match.group(1))


def test_vertical_chinese_font_is_slightly_smaller_for_shorts():
    header = build_ass_header(358, 640)

    assert style_font_size(header, "Chinese") == 24
    assert style_font_size(header, "English") == 20


def test_horizontal_font_sizes_are_unchanged():
    header = build_ass_header(1920, 1080)

    assert style_font_size(header, "Chinese") == 52
    assert style_font_size(header, "English") == 44


def run_all_tests():
    tests = [
        test_vertical_chinese_font_is_slightly_smaller_for_shorts,
        test_horizontal_font_sizes_are_unchanged,
    ]
    for test in tests:
        test()
        print(f"✅ {test.__name__}")
    print(f"结果: {len(tests)} passed, 0 failed, {len(tests)} total")


if __name__ == "__main__":
    run_all_tests()
