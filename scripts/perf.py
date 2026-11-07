"""Measure conflict detection cost at scale.

The first implementation built `list(combinations(refs, 2))` before filtering,
so 5,000 tools allocated 12.5M tuples regardless of how few of them could
possibly collide. This script measures the current implementation against that
baseline, and checks that a planted hard collision is still found at every size.

    python scripts/perf.py

Numbers are measured, not estimated. Nothing here is extrapolated.
"""

from __future__ import annotations

import statistics
import sys
import time
import tracemalloc
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agentcheckup.conflicts import ToolRef, detect_conflicts  # noqa: E402
from agentcheckup.models import Tool  # noqa: E402

VERBS = ["read", "write", "list", "search", "create", "delete", "update", "fetch"]
NOUNS = ["file", "repo", "issue", "table", "user", "log", "config", "image", "doc", "cache"]


def build(count: int) -> list[ToolRef]:
    """Realistic-ish manifest: mostly distinct names, a few shared nouns."""
    refs: list[ToolRef] = []
    for i in range(count):
        verb = VERBS[i % len(VERBS)]
        noun = NOUNS[(i // len(VERBS)) % len(NOUNS)]
        name = f"{verb}_{noun}_{i}"
        tool = Tool.from_raw(
            {
                "name": name,
                "description": f"{verb.title()} the {noun} at the given path and return its contents.",
                "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
            }
        )
        refs.append(ToolRef(server=f"server{i % 20}", tool=tool))
    return refs


def measure(fn, repeats: int = 3) -> tuple[float, int]:
    """Best-of-N seconds, plus peak traced memory in MiB."""
    times: list[float] = []
    peak = 0
    for _ in range(repeats):
        tracemalloc.start()
        start = time.perf_counter()
        fn()
        times.append(time.perf_counter() - start)
        _, current_peak = tracemalloc.get_traced_memory()
        peak = max(peak, current_peak)
        tracemalloc.stop()
    return statistics.median(times), peak // (1024 * 1024)


def main() -> int:
    print(f"{'tools':>7}  {'pairs':>12}  {'naive MiB':>10}  {'ours s':>8}  {'ours MiB':>9}  {'found':>6}")
    print("-" * 62)

    for count in (50, 200, 1000, 5000):
        refs = build(count)

        # Plant one hard collision so a silent miss is visible.
        planted = Tool.from_raw(
            {
                "name": "read_file_0",  # collides with refs[0]
                "description": "Read a file and return it.",
                "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
            }
        )
        refs_with_plant = refs + [ToolRef(server="planted", tool=planted)]

        pair_count = count * (count - 1) // 2
        _, naive_peak = measure(lambda r=refs: list(combinations(r, 2)), repeats=1)
        seconds, ours_peak = measure(lambda r=refs_with_plant: detect_conflicts(r))

        found = [c for c in detect_conflicts(refs_with_plant) if c.rule == "AGT201"]
        hit = any("planted" in (c.a.server, c.b.server) for c in found)

        print(
            f"{count:>7}  {pair_count:>12,}  {naive_peak:>10}  "
            f"{seconds:>8.3f}  {ours_peak:>9}  {'yes' if hit else 'MISS':>6}"
        )

    print()
    print("naive MiB  = peak traced memory for list(combinations(refs, 2)) alone")
    print("ours s/MiB = the whole detect_conflicts() pass, same input")
    print("found      = a planted AGT201 was reported at that size")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
