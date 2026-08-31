"""Tests for the markdown -> ADF converter (ported verbatim from legacy jirainator).

Pins the two-function surface and the warning surface the push guard depends on:
clean markdown yields no warnings; an unsupported non-h3 heading and a dropped
HTML comment each surface a tracked downgrade so the write path can refuse.
"""

import adf
import pytest


def test_clean_markdown_has_no_warnings():
    doc, warnings = adf.markdown_to_adf_with_warnings("### H\n\n- a\n- b\n")
    assert warnings == []
    assert doc["type"] == "doc" and doc["version"] == 1


def test_unsupported_h1_emits_warning():
    _doc, warnings = adf.markdown_to_adf_with_warnings("# Title\n")
    assert any("non-h3 heading" in w for w in warnings)


def test_dropped_html_comment_is_a_tracked_downgrade():
    _doc, warnings = adf.markdown_to_adf_with_warnings("<!-- TODO: x -->\n")
    assert any("dropped HTML comment" in w for w in warnings)


@pytest.mark.parametrize(
    "markdown",
    [
        "> quoted text\n",
        "| Column | Value |\n| --- | --- |\n",
        "Text with <strong>raw HTML</strong>.\n",
        "Text with <!-- TODO: inline --> marker.\n",
    ],
)
def test_unsupported_blocks_emit_warning(markdown):
    _doc, warnings = adf.markdown_to_adf_with_warnings(markdown)
    assert any("unsupported block" in warning for warning in warnings)


def test_html_example_in_inline_code_has_no_warning():
    doc, warnings = adf.markdown_to_adf_with_warnings("Use `<div>` here.\n")
    assert warnings == []
    assert doc["content"][0]["content"][1] == {
        "type": "text",
        "text": "<div>",
        "marks": [{"type": "code"}],
    }


def test_multiline_html_comment_emits_warning():
    _doc, warnings = adf.markdown_to_adf_with_warnings(
        "<!-- TODO:\nAdd reviewed content\n-->\n"
    )
    assert any("HTML comment" in warning for warning in warnings)


def test_soft_wrapped_lines_form_one_paragraph():
    doc, warnings = adf.markdown_to_adf_with_warnings(
        "First wrapped line\ncontinues here.\n\nSecond paragraph.\n"
    )
    assert warnings == []
    assert len(doc["content"]) == 2
    assert doc["content"][0]["content"] == [
        {"type": "text", "text": "First wrapped line continues here."}
    ]


def test_table_without_outer_pipes_emits_warning():
    _doc, warnings = adf.markdown_to_adf_with_warnings(
        "Name | Value\n--- | ---\nalpha | beta\n"
    )
    assert any("table" in warning for warning in warnings)


def test_back_compat_wrapper_discards_warnings():
    doc = adf.markdown_to_adf("### Heading\n")
    assert doc["type"] == "doc"


def test_empty_input_yields_single_empty_paragraph():
    doc = adf.markdown_to_adf("")
    assert doc["content"] == [{"type": "paragraph", "content": []}]
