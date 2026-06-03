#!/usr/bin/env python3
"""Tests for generated English subtitle visibility decisions."""

from subtitle_display import decide_show_english, effective_show_english_value


def test_vertical_detected_yes_hides_english():
    assert decide_show_english(1080, 1920, "auto", "yes") is False


def test_vertical_detected_no_shows_english():
    assert decide_show_english(1080, 1920, "auto", "no") is True


def test_vertical_detected_unknown_hides_english():
    # 竖屏 + 检测未知 → 只留中文（源英文常在中部，检测器扫不到，宁可不重复）
    assert decide_show_english(1080, 1920, "auto", "unknown") is False


def test_horizontal_shows_english():
    assert decide_show_english(1920, 1080, "auto", "yes") is True


def test_explicit_overrides_auto():
    assert effective_show_english_value(1080, 1920, "yes", "yes") == "yes"
    assert effective_show_english_value(1920, 1080, "no", "unknown") == "no"


def run_all_tests():
    tests = [
        test_vertical_detected_yes_hides_english,
        test_vertical_detected_no_shows_english,
        test_vertical_detected_unknown_hides_english,
        test_horizontal_shows_english,
        test_explicit_overrides_auto,
    ]
    for test in tests:
        test()
        print(f"✅ {test.__name__}")
    print(f"结果: {len(tests)} passed, 0 failed, {len(tests)} total")


if __name__ == "__main__":
    run_all_tests()