#!/usr/bin/env python3
"""Sentence splitting with an nltk fallback for lightweight environments."""

from __future__ import annotations

import re


def _regex_sent_tokenize(text: str) -> list[str]:
    text = " ".join(text.split())
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def sent_tokenize(text: str) -> list[str]:
    try:
        import nltk
        try:
            nltk.data.find("tokenizers/punkt_tab")
        except LookupError:
            nltk.download("punkt_tab", quiet=True)
        from nltk.tokenize import sent_tokenize as nltk_sent_tokenize

        return nltk_sent_tokenize(text)
    except Exception:
        return _regex_sent_tokenize(text)
