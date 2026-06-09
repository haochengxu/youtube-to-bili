#!/usr/bin/env python3
"""Tests for subtitle mode selection."""

from subtitle_mode import choose_subtitle_mode


def test_auto_short_stays_auto():
    assert choose_subtitle_mode(180, "auto") == "auto"


def test_auto_long_stays_auto():
    assert choose_subtitle_mode(1200, "auto") == "auto"


def test_manual_override():
    assert choose_subtitle_mode(1200, "precise") == "precise"
    assert choose_subtitle_mode(30, "fast") == "fast"


def test_invalid_mode():
    try:
        choose_subtitle_mode(30, "slow")
    except ValueError:
        return
    raise AssertionError("invalid mode should raise ValueError")


def run_all_tests():
    tests = [
        test_auto_short_stays_auto,
        test_auto_long_stays_auto,
        test_manual_override,
        test_invalid_mode,
    ]
    for test in tests:
        test()
        print(f"✅ {test.__name__}")
    print(f"结果: {len(tests)} passed, 0 failed, {len(tests)} total")


if __name__ == "__main__":
    run_all_tests()
