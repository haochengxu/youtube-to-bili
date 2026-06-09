#!/usr/bin/env python3
"""Choose subtitle timing mode for pipeline.sh."""

from __future__ import annotations

import sys


VALID_MODES = {"auto", "fast", "precise"}


def choose_subtitle_mode(
    duration_seconds: float,
    requested: str = "auto",
    threshold_seconds: int | None = None,
) -> str:
    requested = (requested or "auto").strip().lower()
    if requested not in VALID_MODES:
        raise ValueError(f"invalid subtitle mode: {requested}")
    if requested != "auto":
        return requested
    return "auto"


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: python3 subtitle_mode.py <duration_seconds> [auto|fast|precise]", file=sys.stderr)
        sys.exit(1)

    try:
        duration = float(sys.argv[1] or 0)
        mode = choose_subtitle_mode(duration, sys.argv[2] if len(sys.argv) > 2 else "auto")
    except ValueError as exc:
        print(exc, file=sys.stderr)
        sys.exit(2)

    print(mode)


if __name__ == "__main__":
    main()
