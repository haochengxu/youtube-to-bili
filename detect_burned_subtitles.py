#!/usr/bin/env python3
"""Detect likely burned-in subtitles near the bottom of a video frame."""

from __future__ import annotations

import math
import shutil
import subprocess
import sys
from pathlib import Path


SAMPLE_COUNT = 5
SCALE_WIDTH = 160
SCALE_HEIGHT = 60
BRIGHT_THRESHOLD = 210
DARK_THRESHOLD = 70
EDGE_THRESHOLD = 85


def probe_duration(video_path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ffprobe failed")
    return max(0.0, float(result.stdout.strip() or 0.0))


def sample_timestamps(duration_seconds: float, sample_count: int = SAMPLE_COUNT) -> list[float]:
    if duration_seconds <= 0:
        return [0.0]
    start_ratio = 0.15
    end_ratio = 0.85
    if sample_count <= 1:
        return [duration_seconds * 0.5]
    step = (end_ratio - start_ratio) / (sample_count - 1)
    return [duration_seconds * (start_ratio + step * index) for index in range(sample_count)]


def extract_bottom_band(video_path: Path, timestamp_seconds: float) -> bytes:
    vf = (
        "crop=iw*0.8:ih*0.28:iw*0.1:ih*0.64,"
        f"scale={SCALE_WIDTH}:{SCALE_HEIGHT},format=gray"
    )
    result = subprocess.run(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-ss",
            f"{timestamp_seconds:.3f}",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-vf",
            vf,
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            "-",
        ],
        capture_output=True,
        timeout=20,
        check=False,
    )
    if result.returncode != 0 or not result.stdout:
        raise RuntimeError(result.stderr.strip() or "ffmpeg frame extraction failed")
    return result.stdout


def _row_metrics(row: bytes) -> tuple[float, float, float]:
    width = len(row)
    bright = sum(1 for pixel in row if pixel >= BRIGHT_THRESHOLD) / width
    dark = sum(1 for pixel in row if pixel <= DARK_THRESHOLD) / width
    edges = sum(1 for left, right in zip(row, row[1:]) if abs(right - left) >= EDGE_THRESHOLD) / max(1, width - 1)
    return bright, dark, edges


def score_bottom_band(raw_pixels: bytes, width: int = SCALE_WIDTH, height: int = SCALE_HEIGHT) -> int:
    if len(raw_pixels) != width * height:
        return 0

    candidate_rows = 0
    high_edge_rows = 0
    max_cluster = 0
    high_edge_cluster = 0
    max_high_edge_cluster = 0
    current_cluster = 0
    bright_total = 0.0
    edge_total = 0.0

    for row_index in range(height):
        row = raw_pixels[row_index * width:(row_index + 1) * width]
        bright, dark, edges = _row_metrics(row)
        bright_total += bright
        edge_total += edges
        looks_like_subtitle_row = 0.02 <= bright <= 0.45 and dark >= 0.12 and edges >= 0.10
        # Some burned-in captions are white text over a bright video area, so the
        # dark-pixel ratio can be low after scaling. Consecutive high-contrast
        # rows in a plausible subtitle band are still a useful signal.
        looks_like_high_edge_text = 0.08 <= bright <= 0.55 and dark >= 0.03 and edges >= 0.12
        if looks_like_subtitle_row:
            candidate_rows += 1
            current_cluster += 1
            max_cluster = max(max_cluster, current_cluster)
        else:
            current_cluster = 0
        if looks_like_high_edge_text:
            high_edge_rows += 1
            high_edge_cluster += 1
            max_high_edge_cluster = max(max_high_edge_cluster, high_edge_cluster)
        else:
            high_edge_cluster = 0

    avg_bright = bright_total / height
    avg_edges = edge_total / height

    if max_cluster >= 2 and candidate_rows >= 3 and avg_edges >= 0.08 and avg_bright >= 0.02:
        return 1
    if max_high_edge_cluster >= 2 and high_edge_rows >= 2:
        return 1
    if candidate_rows == 0 and avg_edges <= 0.04 and avg_bright <= 0.015:
        return -1
    return 0


def detect_burned_subtitles(video_path: str | Path) -> str:
    path = Path(video_path)
    if not path.exists() or not path.is_file():
        return "unknown"
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        return "unknown"

    try:
        duration = probe_duration(path)
        timestamps = sample_timestamps(duration)
        scores = [score_bottom_band(extract_bottom_band(path, timestamp)) for timestamp in timestamps]
    except Exception:
        return "unknown"

    positives = sum(1 for score in scores if score > 0)
    negatives = sum(1 for score in scores if score < 0)

    if positives >= max(2, math.ceil(len(scores) / 2)) and positives > negatives:
        return "yes"
    if negatives >= max(3, len(scores) - 1) and positives == 0:
        return "no"
    return "unknown"


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python3 detect_burned_subtitles.py <video_path>", file=sys.stderr)
        sys.exit(1)
    print(detect_burned_subtitles(sys.argv[1]))


if __name__ == "__main__":
    main()
