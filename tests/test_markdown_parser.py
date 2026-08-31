import pytest
from markdown_parser import parse_markdown, MarkdownParseError
from models import IssueType


def _write(tmp_path, text):
    p = tmp_path / "tickets.md"
    p.write_text(text, encoding="utf-8")
    return p


def test_parses_two_blocks_with_yaml_and_summary(tmp_path):
    md = (
        "## Login Form\n\n"
        "```yaml\nproject_id: PROJ\nissue_type: story\ncomponent: Frontend\n"
        "epic_key: PROJ-100\nstory_points: 5\n```\n\n"
        "### Description\nLog in with email.\n\n"
        "---\n\n"
        "## Auth Middleware\n\n"
        "```yaml\nproject_id: PROJ\nissue_type: task\ncomponent: Backend\n```\n\n"
        "Configure JWT.\n"
    )
    result = parse_markdown(_write(tmp_path, md))
    assert [t.summary for t in result.tickets] == ["Login Form", "Auth Middleware"]
    first = result.tickets[0]
    assert first.issue_type == IssueType.STORY
    assert first.project_id == "PROJ"
    assert first.epic_key == "PROJ-100"
    assert first.story_points == 5


def test_epic_with_story_points_is_rejected(tmp_path):
    md = (
        "## Big Epic\n\n```yaml\nproject_id: PROJ\nissue_type: epic\n"
        "component: Platform\nstory_points: 8\n```\n\nOverview.\n"
    )
    with pytest.raises(MarkdownParseError) as exc:
        parse_markdown(_write(tmp_path, md))
    assert any("story_points" in e for e in exc.value.errors)


@pytest.mark.parametrize(
    "relationship_fields",
    [
        "link_to: PROJ-50\nlink_type: blocks\n",
        "epic_key: NEW\n",
    ],
)
def test_unsupported_relationship_markers_are_rejected(tmp_path, relationship_fields):
    md = (
        "## Linked Story\n\n```yaml\nproject_id: PROJ\nissue_type: story\n"
        f"component: Platform\n{relationship_fields}```\n\nBody.\n"
    )

    with pytest.raises(MarkdownParseError) as exc:
        parse_markdown(_write(tmp_path, md))

    assert any("not supported" in error for error in exc.value.errors)


def test_horizontal_rule_inside_description_is_not_a_ticket_delimiter(tmp_path):
    md = (
        "## Login Form\n\n```yaml\nproject_id: PROJ\nissue_type: story\n"
        "component: Frontend\n```\n\nBefore rule.\n\n---\n\nAfter rule.\n"
    )

    result = parse_markdown(_write(tmp_path, md))

    assert len(result.tickets) == 1
    assert "Before rule.\n\n---\n\nAfter rule." in result.tickets[0].description


def test_epic_key_accepts_digits_after_first_project_character(tmp_path):
    md = (
        "## Login Form\n\n```yaml\nproject_id: APP2\nissue_type: story\n"
        "component: Frontend\nepic_key: APP2-123\n```\n\nBody.\n"
    )

    result = parse_markdown(_write(tmp_path, md))

    assert result.tickets[0].epic_key == "APP2-123"


def test_horizontal_rule_before_h2_without_yaml_stays_in_description(tmp_path):
    md = (
        "## Login Form\n\n```yaml\nproject_id: PROJ\nissue_type: story\n"
        "component: Frontend\n```\n\nBefore rule.\n\n---\n\n"
        "## Design notes\n\nAfter rule.\n"
    )

    result = parse_markdown(_write(tmp_path, md))

    assert len(result.tickets) == 1
    assert "## Design notes" in result.tickets[0].description
