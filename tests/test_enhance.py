"""Tests for the enrichment helpers ported from legacy jirainator.

The one real design change from the legacy port is ``select_template``: it now
reads a per-config, user-editable ``<issuetype>.md`` file from a templates dir
(AC #4: config/profile-driven, not a hardcoded ``_TEMPLATES`` dict). The pure
helpers (parse_args, find_todo_sections, render_diff, build_edit_payload,
is_stale_write) are ported verbatim and covered here too.
"""

import pytest

import enhance
from models import IssueType


def _seed(tmp_path):
    (tmp_path / "story.md").write_text(
        "### Description\n<!-- TODO: Add description -->\n", encoding="utf-8"
    )
    return tmp_path


def test_select_template_reads_file_by_issue_type(tmp_path):
    _seed(tmp_path)
    body = enhance.select_template(IssueType.STORY, tmp_path)
    assert "### Description" in body


def test_select_template_accepts_case_insensitive_string(tmp_path):
    _seed(tmp_path)
    assert enhance.select_template("Story", tmp_path) == enhance.select_template(
        IssueType.STORY, tmp_path
    )


def test_select_template_resolves_alias(tmp_path):
    (tmp_path / "research.md").write_text("### Context/Description\n", encoding="utf-8")
    assert enhance.select_template(
        "research spike", tmp_path
    ) == enhance.select_template(IssueType.RESEARCH, tmp_path)


def test_select_template_unknown_type_raises(tmp_path):
    with pytest.raises(ValueError):
        enhance.select_template("nonsense", tmp_path)


def test_select_template_missing_file_raises(tmp_path):
    # A known issue type whose template file was not seeded is a broken install,
    # not a silent empty template: fail loud.
    with pytest.raises(ValueError):
        enhance.select_template(IssueType.EPIC, tmp_path)


def test_parse_args_requires_key_first():
    with pytest.raises(ValueError):
        enhance.parse_args(["--push", "PROJ-1"])


def test_parse_args_parses_flags():
    args = enhance.parse_args(["PROJ-1", "--push", "--interactive"])
    assert args.issue_key == "PROJ-1"
    assert args.push is True
    assert args.interactive is True


@pytest.mark.parametrize("key", ["R2D2-3", "PRODUCT_2013-4"])
def test_parse_args_accepts_jira_project_key_characters(key):
    assert enhance.parse_args([key]).issue_key == key


def test_find_todo_sections_one_per_heading():
    md = "### A\n<!-- TODO: x -->\n<!-- TODO: y -->\n### B\nno marker\n"
    sections = enhance.find_todo_sections(md)
    assert [s.heading for s in sections] == ["### A"]


def test_build_edit_payload_rejects_blank():
    with pytest.raises(ValueError):
        enhance.build_edit_payload("   \n")


def test_is_stale_write_detects_changed_baseline():
    assert enhance.is_stale_write("### A\ncontent\n", "### A\nchanged\n") is True
    assert enhance.is_stale_write("### A\ncontent\n", "### A\ncontent  \n") is False
