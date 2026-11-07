"""Rough token estimation with no tokenizer dependency.

Why not tiktoken: it ships native wheels per platform and pulls a network
download at first use. For a linter that runs in CI on arbitrary machines that
is a bad trade. The heuristic below is intentionally conservative and is
documented as an estimate everywhere it surfaces.

Calibration: OpenAI's cl100k / o200k families average ~4 characters per token
for English prose and ~1 token per CJK character. JSON punctuation is denser
than prose, so we apply a slight structural discount.
"""

from __future__ import annotations

import json
import unicodedata
from typing import Any

_CJK_RANGES = (
    (0x3040, 0x30FF),  # kana
    (0x3400, 0x4DBF),  # CJK ext A
    (0x4E00, 0x9FFF),  # CJK unified
    (0xAC00, 0xD7AF),  # hangul
    (0xF900, 0xFAFF),  # CJK compat
    (0xFF00, 0xFFEF),  # fullwidth forms
)


def _is_cjk(ch: str) -> bool:
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in _CJK_RANGES)


def estimate_tokens(text: str) -> int:
    """Estimate token count for a string."""
    if not text:
        return 0
    cjk = 0
    other = 0
    for ch in text:
        if _is_cjk(ch):
            cjk += 1
        else:
            other += 1
    return cjk + max(1, round(other / 4)) if other else cjk


def estimate_json_tokens(payload: Any) -> int:
    """Estimate tokens for a JSON-serialisable structure."""
    dumped = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return estimate_tokens(dumped)


def manifest_tokens(tools: list[Any]) -> int:
    """Estimate how many tokens the whole tool manifest costs in context.

    This is the number an agent pays on *every* request, so it matters more
    than any single description.
    """
    return estimate_json_tokens([t.raw if hasattr(t, "raw") else t for t in tools])


def has_invisible_chars(text: str) -> list[str]:
    """Return code points of characters that hide text from human review."""
    suspects: list[str] = []
    for ch in text:
        if ch in ("\u200b", "\u200c", "\u200d", "\u2060", "\ufeff") or unicodedata.category(ch) == "Cf":
            suspects.append(f"U+{ord(ch):04X}")
    return sorted(set(suspects))
