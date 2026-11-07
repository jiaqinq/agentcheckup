"""Regression guard on the labelled collision benchmark.

`scripts/benchmark.py` prints the numbers for humans; this keeps them from
silently decaying. The floors are set a little below the measured values so a
small, deliberate trade-off does not fail the build, but a real regression does.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agentcheckup.conflicts import ToolRef, detect_conflicts  # noqa: E402
from agentcheckup.models import Tool  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "collision_benchmark.json"

MIN_PRECISION = 0.90
MIN_RECALL = 0.90


def to_ref(side: dict) -> ToolRef:
    tool = Tool.from_raw(
        {
            "name": side["name"],
            "description": side["description"],
            "inputSchema": {
                "type": "object",
                "properties": {"path": {"type": "string", "pattern": "^.*$"}},
                "additionalProperties": False,
            },
        }
    )
    return ToolRef(server=side["server"], tool=tool)


def score() -> tuple[float, float, list[str], list[str]]:
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))
    tp = fp = fn = 0
    false_positives: list[str] = []
    false_negatives: list[str] = []

    for case in cases:
        found = detect_conflicts([to_ref(case["a"]), to_ref(case["b"])])
        predicted = bool(found)
        if predicted and case["conflict"]:
            tp += 1
        elif predicted and not case["conflict"]:
            fp += 1
            false_positives.append(case["id"])
        elif not predicted and case["conflict"]:
            fn += 1
            false_negatives.append(case["id"])

    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return precision, recall, false_positives, false_negatives


def test_benchmark_precision_and_recall_hold():
    precision, recall, false_positives, false_negatives = score()
    assert precision >= MIN_PRECISION, f"precision dropped to {precision:.3f}; FP: {false_positives}"
    assert recall >= MIN_RECALL, f"recall dropped to {recall:.3f}; FN: {false_negatives}"


def test_benchmark_covers_both_labels():
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))
    positives = sum(1 for c in cases if c["conflict"])
    negatives = len(cases) - positives
    # A benchmark that drifts to one class measures nothing.
    assert positives >= 10, positives
    assert negatives >= 10, negatives


def test_benchmark_includes_chinese_cases():
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))
    chinese = [c for c in cases if any("\u4e00" <= ch <= "\u9fff" for ch in c["a"]["name"])]
    assert len(chinese) >= 4, len(chinese)
