from __future__ import annotations

from agentcheckup.conflicts import ToolRef, detect_conflicts, jaccard, tokens
from agentcheckup.engine import lint_audit
from agentcheckup.models import ServerConfig, Tool


def tool(name: str, description: str = "") -> Tool:
    return Tool.from_raw(
        {
            "name": name,
            "description": description
            or f"{name} does something useful. Use this only in tests; prefer `other`. Returns a value.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
            "annotations": {"readOnlyHint": True, "destructiveHint": False},
        }
    )


def ref(server: str, name: str, description: str = "") -> ToolRef:
    return ToolRef(server=server, tool=tool(name, description))


# --------------------------------------------------------------------------- #
# similarity primitives
# --------------------------------------------------------------------------- #


def test_tokens_drops_stopwords_and_stems_plurals():
    assert "the" not in tokens("the file")
    assert "file" in tokens("files")
    assert tokens("") == set()


def test_jaccard_bounds():
    assert jaccard(set(), {"a"}) == 0.0
    assert jaccard({"a"}, {"a"}) == 1.0
    assert jaccard({"a", "b"}, {"a", "c"}) == 1 / 3


# --------------------------------------------------------------------------- #
# conflict detection
# --------------------------------------------------------------------------- #


def test_identical_names_across_servers_is_an_error():
    conflicts = detect_conflicts([ref("files", "read_file"), ref("git", "read_file")])
    assert [c.rule for c in conflicts] == ["AGT201"]
    assert conflicts[0].severity.value == "error"


def test_same_name_within_one_server_is_not_a_conflict():
    # A duplicate inside one server is AGT004's job, not a cross-server conflict.
    assert detect_conflicts([ref("files", "read_file"), ref("files", "read_file")]) == []


def test_plural_variants_are_near_duplicates():
    conflicts = detect_conflicts([ref("a", "read_files"), ref("b", "read_file")])
    assert "AGT202" in {c.rule for c in conflicts}


def test_overlapping_descriptions_are_flagged():
    desc_a = "Search public repositories by keyword and return matching repository names."
    desc_b = "Search private repositories by keyword and return matching repository names."
    # Different names, so this is the soft case (AGT203) rather than a hard
    # collision (AGT201).
    conflicts = detect_conflicts(
        [ref("github", "search_public", desc_a), ref("docs", "search_private", desc_b)]
    )
    assert "AGT203" in {c.rule for c in conflicts}


def test_unrelated_tools_are_not_flagged():
    a = ref("files", "read_file", "Read a file from the sandbox and return its contents.")
    b = ref("jira", "create_ticket", "Create a Jira issue with a title, body and assignee.")
    assert detect_conflicts([a, b]) == []


def test_similar_description_without_shared_noun_is_not_flagged():
    # Both are "search" but about different objects; sharing a head noun is the
    # guard that keeps the false-positive rate down.
    a = ref("github", "search_repositories", "Search repositories by name across the org.")
    b = ref("docs", "search_documents", "Search documents by title across the workspace.")
    assert detect_conflicts([a, b]) == []


def test_conflict_becomes_a_finding_with_both_sides():
    conflicts = detect_conflicts([ref("files", "read_file"), ref("git", "read_file")])
    finding = conflicts[0].as_finding()
    assert "files/read_file" in finding.tool
    assert "git/read_file" in finding.tool
    assert finding.hint


# --------------------------------------------------------------------------- #
# audit assembly
# --------------------------------------------------------------------------- #


def test_audit_splits_conflicts_from_risks():
    servers = [
        ServerConfig(name="files", command="npx", args=["-y", "server-filesystem", "/"]),
        ServerConfig(name="git", command="npx", args=["-y", "server-git"]),
    ]
    tools = {
        "files": [tool("read_file")],
        "git": [tool("read_file")],
    }
    report = lint_audit(servers, tools)
    assert report.kind == "audit"
    assert report.server_count == 2
    assert report.tool_count == 2
    assert [f.rule for f in report.conflicts()] == ["AGT201"]
    # AGT104 (root grant) and AGT101 (unpinned) must land in the risks section.
    risk_ids = {f.rule for f in report.risks()}
    assert "AGT104" in risk_ids
    assert "AGT101" in risk_ids


def test_audit_reports_unreachable_servers():
    servers = [ServerConfig(name="broken", command="definitely-not-a-real-command-xyz")]
    report = lint_audit(servers, {}, failures={"broken": "spawn failed"})
    assert "AGT105" in {f.rule for f in report.findings}


def test_audit_tokens_sum_across_servers():
    servers = [ServerConfig(name="a", command="x"), ServerConfig(name="b", command="y")]
    tools = {"a": [tool("alpha_tool")], "b": [tool("beta_tool")]}
    report = lint_audit(servers, tools)
    assert report.tokens > 0


# --------------------------------------------------------------------------- #
# CJK support
# --------------------------------------------------------------------------- #


def test_cjk_runs_become_character_bigrams():
    assert tokens("读取文件") == {"读取", "取文", "文件"}


def test_single_cjk_character_is_kept_whole():
    assert tokens("读") == {"读"}


def test_cjk_and_latin_mix():
    got = tokens("read 文件")
    assert "read" in got
    assert "文件" in got


def test_chinese_near_duplicates_are_flagged():
    """Before CJK support this pair produced two empty token sets and no finding."""
    a = ref("文件服务", "读取文件", "读取指定路径的文件内容并返回文本")
    b = ref("文档服务", "读取文档", "读取指定路径的文件内容并返回字符串")
    assert "AGT203" in {c.rule for c in detect_conflicts([a, b])}


def test_chinese_unrelated_tools_are_not_flagged():
    a = ref("文件服务", "读取文件", "读取指定路径的文件内容并返回文本")
    b = ref("文件服务", "删除文件", "删除指定路径的文件")
    assert detect_conflicts([a, b]) == []


def test_english_scores_are_unchanged_by_cjk_support():
    """The CJK path must not touch Latin tokenisation."""
    assert tokens("Read a file") == {"read", "file"}


# --------------------------------------------------------------------------- #
# Scale
# --------------------------------------------------------------------------- #


def test_hard_collision_is_found_in_a_large_manifest():
    """Grouping must not depend on the pair count staying small.

    The previous implementation built every combination up front (763 MiB at
    5,000 tools) and only then filtered. This asserts the answer survives the
    rewrite; scripts/perf.py records the cost.
    """
    refs = [
        ref(f"server{i % 20}", f"tool_{i}", f"Operation {i} on a resource.")
        for i in range(2000)
    ]
    refs.append(ref("planted", "tool_0", "A different tool with the same name."))

    found = detect_conflicts(refs)
    assert any("planted" in (c.a.server, c.b.server) for c in found if c.rule == "AGT201")


def test_soft_phase_is_bounded_by_the_budget():
    """A pathological manifest must not run unbounded soft comparisons."""
    refs = [
        ref(f"server{i % 50}", f"read_file_{i}", "Read a file and return its text.")
        for i in range(3000)
    ]
    # A tiny budget keeps the call fast; the point is that it returns at all.
    found = detect_conflicts(refs, max_pairs=100)
    assert isinstance(found, list)
