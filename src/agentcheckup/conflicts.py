"""Cross-server tool conflict detection.

This is the reason the tool exists. Every other scanner looks at one server at a
time; nobody asks what happens when five servers are loaded at once and three of
them expose something called ``search``.

Two servers cannot see each other. The model can, and it has no way to know that
``github.search`` and ``docs.search`` are different things - it gets a flat list
of 47 tools and picks by description similarity. When two descriptions overlap,
selection becomes a coin flip that looks like model flakiness.

No dependencies: similarity is token-set Jaccard over normalised text. An
embedding would be better, but it would also mean a model download, a network
call, or a 200MB wheel - and then the linter stops working on a plane.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import combinations

from .models import Finding, Severity, Tool

#: Words that carry no discriminating signal in a tool description.
STOPWORDS = frozenset(
    {
        "a", "an", "the", "this", "that", "these", "those",
        "is", "are", "was", "were", "be", "been", "being",
        "and", "or", "but", "if", "then", "than", "so", "as",
        "at", "by", "for", "from", "in", "into", "of", "on", "to", "with",
        "it", "its", "you", "your", "we", "our", "they", "them", "their",
        "he", "she", "his", "her",
        "can", "could", "may", "might", "must", "shall", "should", "will", "would",
        "do", "does", "did", "done",
        "make", "makes", "made", "use", "uses", "used", "using",
        "tool", "tools", "function", "functions", "call", "calls", "called",
        "return", "returns", "returned", "value", "values", "result", "results",
        "given", "specify", "specified", "provide", "provides",
    }
)

WORD = re.compile(r"[a-z0-9]+")

#: CJK ideographs, extension A included. Matched per character because Chinese
#: has no word delimiters and a real segmenter would be a dependency.
CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")

#: Word boundary inside camelCase and PascalCase, including acronym runs:
#: ``readFiles`` -> ``read Files``, ``parseHTML`` -> ``parse HTML``.
#: Without this, ``readFiles`` was a single token and could never match
#: ``read_files`` — two spellings of the same tool looked unrelated.
CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


@dataclass(frozen=True)
class ToolRef:
    """A tool plus the server it came from."""

    server: str
    tool: Tool

    @property
    def qualified(self) -> str:
        return f"{self.server}/{self.tool.name}"


@dataclass(frozen=True)
class Conflict:
    rule: str
    severity: Severity
    a: ToolRef
    b: ToolRef
    similarity: float
    message: str
    hint: str

    def as_finding(self) -> Finding:
        return Finding(
            rule=self.rule,
            severity=self.severity,
            message=self.message,
            tool=f"{self.a.qualified} <-> {self.b.qualified}",
            hint=self.hint,
            where=f"similarity={self.similarity:.2f}",
        )


def _stem(word: str) -> str:
    """Crude English plural stripping.

    Deliberately not a real stemmer: `read_files` and `read_file` must collapse
    to the same token, and that is the only job. A full Porter stemmer would be
    a dependency for no benefit.
    """
    if len(word) <= 3:
        return word
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith(("ses", "xes", "zes", "ches", "shes")):
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _cjk_tokens(text: str) -> set[str]:
    """Character bigrams over every CJK run.

    Chinese has no spaces, so ``WORD`` returns nothing and two Chinese tools
    would look like two empty sets — silently, which is the worst outcome. A real
    segmenter is a dependency; character bigrams are the standard cheap
    substitute: 读取文件 -> 读取, 取文, 文件.

    A single-character run is kept whole, so 读 still matches 读.
    """
    out: set[str] = set()
    for run in CJK.findall(text):
        if len(run) == 1:
            out.add(run)
        else:
            out.update(run[i : i + 2] for i in range(len(run) - 1))
    return out


def tokens(text: str) -> set[str]:
    """Lowercase word set, stopwords removed, crude plural stemming, plus CJK."""
    latin = {
        _stem(w)
        for w in WORD.findall(text.lower())
        if w not in STOPWORDS and len(w) > 1
    }
    return latin | _cjk_tokens(text)


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    union = a | b
    return len(a & b) / len(union)


def name_tokens(name: str) -> set[str]:
    spaced = CAMEL.sub(" ", name)
    latin = {_stem(w) for w in WORD.findall(spaced.lower()) if len(w) > 1}
    return latin | _cjk_tokens(name)


def similarity(a: ToolRef, b: ToolRef) -> float:
    """Blend name and description overlap.

    Name overlap matters more when it is exact, because that is a hard
    collision rather than a soft one.
    """
    name_sim = jaccard(name_tokens(a.tool.name), name_tokens(b.tool.name))
    desc_sim = jaccard(tokens(a.tool.description), tokens(b.tool.description))
    return round(0.45 * name_sim + 0.55 * desc_sim, 3)


def is_ambiguous(a: ToolRef, b: ToolRef, threshold: float = 0.55) -> tuple[bool, float]:
    """Decide whether two tools are genuinely confusable.

    Two signals, either is sufficient:

    - the descriptions overlap heavily (>= 0.65) and the names share a head
      noun: the model reads the description, so this is the primary signal;
    - the blended score clears ``threshold``.

    Requiring a shared noun is what keeps ``search_repositories`` and
    ``search_documents`` apart. Without it the false-positive rate made the
    whole report untrustworthy.
    """
    name_sim = jaccard(name_tokens(a.tool.name), name_tokens(b.tool.name))
    desc_sim = jaccard(tokens(a.tool.description), tokens(b.tool.description))
    blended = round(0.45 * name_sim + 0.55 * desc_sim, 3)

    if not _same_object(a, b):
        return False, blended
    return (desc_sim >= 0.65 or blended >= threshold), blended


def _same_object(a: ToolRef, b: ToolRef) -> bool:
    """Two names sharing a head noun are more likely to collide.

    ``search_docs`` and ``search_code`` both end in a different noun, so they are
    probably fine. ``search`` and ``search_docs`` share one, so they are not.
    """
    ta, tb = name_tokens(a.tool.name), name_tokens(b.tool.name)
    return bool(ta & tb)


#: Cap on findings emitted for one group of identically-named tools. A manifest
#: where 200 servers all expose `read_file` has one problem, not 19,900.
MAX_PER_GROUP = 200


def _cross_server_pairs(group: list[ToolRef]):
    """Pairs from different servers. Same-server duplicates are AGT004's job."""
    for a, b in combinations(group, 2):
        if a.server != b.server:
            yield a, b


def _soft_candidates(refs: list[ToolRef], budget: int):
    """Pairs that share at least one name token, rarest tokens first.

    ``is_ambiguous`` requires a shared name token, so an inverted index over
    those tokens yields exactly the pairs worth scoring. Enumerating all
    ``combinations`` instead meant 5,000 tools produced 12.5M tuples in memory
    before any filtering happened.

    Rarest tokens are expanded first so the budget is spent on the most
    discriminating evidence. A token carried by a very large number of tools is
    expanded last, which is also the cheapest way to keep the work bounded.
    """
    postings: dict[str, list[int]] = {}
    for index, ref in enumerate(refs):
        for token in name_tokens(ref.tool.name):
            postings.setdefault(token, []).append(index)

    seen: set[tuple[int, int]] = set()
    for token in sorted(postings, key=lambda t: len(postings[t])):
        members = postings[token]
        if len(members) < 2:
            continue
        for i, j in combinations(members, 2):
            key = (i, j) if i < j else (j, i)
            if key in seen:
                continue
            seen.add(key)
            a, b = refs[key[0]], refs[key[1]]
            if a.server == b.server:
                continue  # same server: a naming problem, not a conflict
            yield a, b
            if len(seen) >= budget:
                return


def detect_conflicts(
    refs: list[ToolRef],
    *,
    threshold: float = 0.55,
    max_pairs: int = 60_000,
) -> list[Conflict]:
    """Find tool pairs across servers that an agent cannot reliably tell apart.

    Hard and normalised collisions are found by grouping, which is O(n) in the
    number of tools. Only the soft-overlap phase enumerates pairs, and it works
    from a token index under a budget — so a large manifest costs time in
    proportion to the evidence, not to the square of the tool count.
    """
    conflicts: list[Conflict] = []
    seen: set[tuple[str, str]] = set()

    def emit(
        rule: str,
        severity: Severity,
        a: ToolRef,
        b: ToolRef,
        similarity: float,
        message: str,
        hint: str,
    ) -> None:
        key = tuple(sorted([a.qualified, b.qualified]))
        if key in seen:
            return
        seen.add(key)
        conflicts.append(
            Conflict(
                rule=rule,
                severity=severity,
                a=a,
                b=b,
                similarity=similarity,
                message=message,
                hint=hint,
            )
        )

    # --- 1. exact collision -------------------------------------------------
    by_name: dict[str, list[ToolRef]] = {}
    for ref in refs:
        by_name.setdefault(ref.tool.name, []).append(ref)

    for group in by_name.values():
        if len(group) < 2:
            continue
        for a, b in _cross_server_pairs(group):
            emit(
                "AGT201",
                Severity.ERROR,
                a,
                b,
                1.0,
                f"Tool name '{a.tool.name}' is exposed by both "
                f"'{a.server}' and '{b.server}'.",
                "Two servers expose the same name and clients resolve that "
                "differently, so the same call can reach either one. Rename "
                "one, or use a gateway that prefixes.",
            )
            if len(conflicts) >= MAX_PER_GROUP:
                break

    # --- 2. normalised collision -------------------------------------------
    # Case is compared exactly in phase 1 because the spec says names SHOULD be
    # treated as case-sensitive; `Read_File` and `read_file` land here instead.
    by_signature: dict[frozenset[str], list[ToolRef]] = {}
    for ref in refs:
        by_signature.setdefault(frozenset(name_tokens(ref.tool.name)), []).append(ref)

    for group in by_signature.values():
        if len(group) < 2:
            continue
        for a, b in _cross_server_pairs(group):
            emit(
                "AGT202",
                Severity.WARNING,
                a,
                b,
                1.0,
                f"Tools '{a.qualified}' and '{b.qualified}' have the same "
                "name once normalised.",
                "Rename one so the model can tell them apart by name alone.",
            )

    # --- 3. capability overlap ---------------------------------------------
    for a, b in _soft_candidates(refs, max_pairs):
        flagged, score = is_ambiguous(a, b, threshold=threshold)
        if not flagged:
            continue
        emit(
            "AGT203",
            Severity.WARNING,
            a,
            b,
            score,
            f"'{a.qualified}' and '{b.qualified}' overlap "
            f"({score:.0%}); the model picks between them at random.",
            "Add a disambiguation clause to both descriptions: "
            '"Use this only for X; use <other tool> for Y."',
        )

    return sorted(conflicts, key=lambda c: (-c.severity.rank, -c.similarity))


def lint_conflicts(refs: list[ToolRef], threshold: float = 0.55) -> list[Finding]:
    return [c.as_finding() for c in detect_conflicts(refs, threshold=threshold)]
