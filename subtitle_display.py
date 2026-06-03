#!/usr/bin/env python3
"""Decide whether generated English subtitles should be shown."""

from __future__ import annotations

import argparse
import sys


FORCE_SHOW_VALUES = {"1", "true", "yes", "on"}
FORCE_HIDE_VALUES = {"0", "false", "no", "off"}
AUTO_VALUES = {"", "auto"}
DETECTOR_VALUES = {"yes", "no", "unknown"}


def normalize_show_english_mode(value: str | None) -> str:
    normalized = (value or "auto").strip().lower()
    if normalized in AUTO_VALUES:
        return "auto"
    if normalized in FORCE_SHOW_VALUES:
        return "yes"
    if normalized in FORCE_HIDE_VALUES:
        return "no"
    raise ValueError(f"invalid SHOW_ENGLISH value: {value}")


def normalize_detector_result(value: str | None) -> str:
    normalized = (value or "unknown").strip().lower()
    if normalized not in DETECTOR_VALUES:
        raise ValueError(f"invalid detector result: {value}")
    return normalized


def get_video_orientation(width: int, height: int) -> str:
    return "vertical" if height > width else "horizontal"


def decide_show_english(width: int, height: int, requested: str = "auto", burned_subtitles: str = "unknown") -> bool:
    mode = normalize_show_english_mode(requested)
    if mode == "yes":
        return True
    if mode == "no":
        return False

    if get_video_orientation(width, height) != "vertical":
        return True

    # 竖屏（短视频）：源通常自带英文字幕（且常在画面中部，底部检测器扫不到）。
    # 为避免与源重复、给中文腾地方，默认只留中文；只有"确认源无内嵌字幕"(detector=no)
    # 才显示我方英文。想强制显示用 SHOW_ENGLISH=yes。
    detector = normalize_detector_result(burned_subtitles)
    return detector == "no"


def effective_show_english_value(width: int, height: int, requested: str = "auto", burned_subtitles: str = "unknown") -> str:
    return "yes" if decide_show_english(width, height, requested, burned_subtitles) else "no"


def main() -> None:
    parser = argparse.ArgumentParser(description="Decide generated English subtitle visibility")
    parser.add_argument("width", type=int)
    parser.add_argument("height", type=int)
    parser.add_argument("requested", nargs="?", default="auto")
    parser.add_argument("burned_subtitles", nargs="?", default="unknown")
    args = parser.parse_args()

    try:
        print(effective_show_english_value(args.width, args.height, args.requested, args.burned_subtitles))
    except ValueError as exc:
        print(exc, file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()