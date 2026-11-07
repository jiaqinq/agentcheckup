"""Naming must follow the spec, not a guess about the spec.

The MCP specification says tool names SHOULD be 1-128 characters of
``[A-Za-z0-9_.-]`` and SHOULD be treated as case-sensitive. The first
implementation enforced ``[A-Za-z0-9_-]{1,64}`` as an *error*, which rejected
`admin.tools.list` — a name the spec itself uses as an example.

These tests pin the spec-derived behaviour so it cannot drift back.
"""

from __future__ import annotations

from agentcheckup.conflicts import ToolRef, detect_conflicts, name_tokens
from agentcheckup.engine import lint_tools
from agentcheckup.models import Severity, Tool


def make(name: str) -> Tool:
    return Tool.from_raw(
        {
            "name": name,
            "description": "Read a file and return its contents as text.",
            "inputSchema": {
                "type": "object",
                "properties": {"path": {"type": "string", "pattern": "^.*$"}},
                "required": ["path"],
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": True},
        }
    )


def rules_for(name: str) -> set[str]:
    report = lint_tools([make(name)])
    return {f.rule for f in report.findings}


def ref(server: str, name: str, description: str = "") -> ToolRef:
    tool = Tool.from_raw(
        {
            "name": name,
            "description": description or "Do a thing with a path and return text.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        }
    )
    return ToolRef(server=server, tool=tool)


# --------------------------------------------------------------------------- #
# AGT001 — the allowed charset
# --------------------------------------------------------------------------- #


def test_dotted_name_is_allowed():
    """`admin.tools.list` is an example in the specification itself."""
    assert "AGT001" not in rules_for("admin.tools.list")


def test_underscore_and_hyphen_are_allowed():
    assert "AGT001" not in rules_for("read_file-v2")


def test_space_is_rejected():
    assert "AGT001" in rules_for("read file")


def test_128_characters_is_the_limit_not_64():
    assert "AGT001" not in rules_for("a" * 128)


def test_129_characters_is_flagged():
    assert "AGT001" in rules_for("a" * 129)


def test_agt001_is_a_warning_because_the_spec_says_should():
    report = lint_tools([make("read file")])
    finding = next(f for f in report.findings if f.rule == "AGT001")
    assert finding.severity is Severity.WARNING


# --------------------------------------------------------------------------- #
# Name normalisation — camelCase, PascalCase, kebab, dot
# --------------------------------------------------------------------------- #


def test_camel_case_splits_into_words():
    assert name_tokens("readFiles") == {"read", "file"}


def test_pascal_case_splits_into_words():
    assert name_tokens("ReadFiles") == {"read", "file"}


def test_snake_kebab_and_dot_all_agree():
    assert name_tokens("read_files") == name_tokens("read-files") == name_tokens("read.files")


def test_camel_and_snake_are_the_same_words():
    assert name_tokens("readFiles") == name_tokens("read_files")


def test_single_word_camel_is_unchanged():
    assert name_tokens("fetch") == {"fetch"}


def test_acronyms_do_not_explode_into_letters():
    """`parseHTML` should be parse + html, not p,a,r,s,e,h,t,m,l."""
    assert name_tokens("parseHTML") == {"parse", "html"}


# --------------------------------------------------------------------------- #
# Collision classification
# --------------------------------------------------------------------------- #


def test_byte_identical_names_are_a_hard_collision():
    found = detect_conflicts([ref("a", "read_file"), ref("b", "read_file")])
    assert [c.rule for c in found] == ["AGT201"]


def test_case_only_difference_is_not_a_hard_collision():
    """The spec says names SHOULD be considered case-sensitive.

    So `Read_File` and `read_file` are distinct tools. They are still worth
    flagging — clients disagree about case folding — but not as an unreachable
    duplicate.
    """
    found = detect_conflicts([ref("a", "read_file"), ref("b", "Read_File")])
    assert [c.rule for c in found] == ["AGT202"]


def test_camel_and_snake_are_a_normalised_collision():
    found = detect_conflicts([ref("a", "readFiles"), ref("b", "read_files")])
    assert [c.rule for c in found] == ["AGT202"]


def test_plain_different_names_stay_quiet():
    found = detect_conflicts(
        [
            ref("a", "read_file", "Read a file and return its text contents."),
            ref("b", "create_ticket", "Create a ticket with a title and an assignee."),
        ]
    )
    assert found == []
