"""Measure conflict detection against a labelled set of tool pairs.

The README used to claim "zero false positives" on the strength of three official
servers that contained no conflicts at all. That is not a measurement. This is:
every pair below was labelled by hand, so precision and recall can be computed
and regressions become visible.

    python scripts/benchmark.py

Labels are the author's, not users'. The criterion applied to each pair:
"would a maintainer reasonably consider these two tools confusable by a model
choosing from one flat list?" A pair is positive when a user picking the wrong
one would get a materially different result.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agentcheckup.conflicts import ToolRef, detect_conflicts  # noqa: E402
from agentcheckup.models import Tool  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "collision_benchmark.json"


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


def main() -> int:
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))

    tp = fp = tn = fn = 0
    false_positives: list[str] = []
    false_negatives: list[str] = []

    for case in cases:
        found = detect_conflicts([to_ref(case["a"]), to_ref(case["b"])])
        predicted = bool(found)
        actual = case["conflict"]

        if predicted and actual:
            tp += 1
        elif predicted and not actual:
            fp += 1
            rules = ",".join(sorted({c.rule for c in found}))
            false_positives.append(f"  {case['id']}  {rules}  {case['why']}")
        elif not predicted and actual:
            fn += 1
            false_negatives.append(f"  {case['id']}  missed  {case['why']}")
        else:
            tn += 1

    total = tp + fp + tn + fn
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    accuracy = (tp + tn) / total if total else 0.0

    print(f"pairs       {total}")
    print(f"positives   {tp + fn}")
    print(f"negatives   {tn + fp}")
    print()
    print(f"true  pos   {tp}")
    print(f"false pos   {fp}")
    print(f"true  neg   {tn}")
    print(f"false neg   {fn}")
    print()
    print(f"precision   {precision:.3f}")
    print(f"recall      {recall:.3f}")
    print(f"f1          {f1:.3f}")
    print(f"accuracy    {accuracy:.3f}")

    if false_positives:
        print("\nfalse positives")
        print("\n".join(false_positives))
    if false_negatives:
        print("\nfalse negatives")
        print("\n".join(false_negatives))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
