import pytest

from markdown_parser import parse_markdown
from create_plan import build_create_plan


def test_build_plan_shapes_createjiraissue_params(tmp_path):
    md = (
        "## Login Form\n\n```yaml\nproject_id: PROJ\nissue_type: story\n"
        "component: Frontend\nepic_key: PROJ-100\nstory_points: 5\n```\n\nBody.\n"
    )
    p = tmp_path / "t.md"
    p.write_text(md, encoding="utf-8")
    plan = build_create_plan(
        parse_markdown(p), story_points_field_id="customfield_12345"
    )
    assert len(plan) == 1
    item = plan[0]
    assert item["projectKey"] == "PROJ"
    assert item["issueTypeName"] == "Story"  # capitalized for MCP
    assert item["summary"] == "Login Form"
    assert item["additional_fields"]["components"] == [{"name": "Frontend"}]
    assert item["parent"] == "PROJ-100"
    assert "parent" not in item["additional_fields"]
    assert item["additional_fields"]["customfield_12345"] == 5
    assert "customfield_10004" not in item["additional_fields"]
    assert "cloudId" not in item  # injected by the command


def test_epic_plan_omits_parent_and_points(tmp_path):
    md = (
        "## Platform Epic\n\n```yaml\nproject_id: PROJ\nissue_type: epic\n"
        "component: Platform\n```\n\nOverview.\n"
    )
    p = tmp_path / "e.md"
    p.write_text(md, encoding="utf-8")
    item = build_create_plan(
        parse_markdown(p), story_points_field_id="customfield_12345"
    )[0]
    assert item["issueTypeName"] == "Epic"
    assert "parent" not in item["additional_fields"]
    assert "customfield_12345" not in item["additional_fields"]


def test_blank_extra_field_is_omitted(tmp_path):
    md = (
        "## Login Form\n\n```yaml\nproject_id: PROJ\nissue_type: story\n"
        "component: Frontend\ncustomfield_12345:\n```\n\nBody.\n"
    )
    path = tmp_path / "blank-extra.md"
    path.write_text(md, encoding="utf-8")

    item = build_create_plan(
        parse_markdown(path), story_points_field_id="customfield_10016"
    )[0]

    assert "customfield_12345" not in item["additional_fields"]


@pytest.mark.parametrize(
    "reserved_field", ["components", "parent", "customfield_12345"]
)
def test_reserved_extra_field_is_rejected(tmp_path, reserved_field):
    md = (
        "## Login Form\n\n```yaml\nproject_id: PROJ\nissue_type: story\n"
        "component: Frontend\nepic_key: PROJ-100\nstory_points: 5\n"
        f"{reserved_field}: override\n```\n\nBody.\n"
    )
    path = tmp_path / "reserved-extra.md"
    path.write_text(md, encoding="utf-8")

    with pytest.raises(ValueError, match="reserved"):
        build_create_plan(
            parse_markdown(path), story_points_field_id="customfield_12345"
        )


def test_research_plan_uses_jira_issue_type_name(tmp_path):
    md = (
        "## Investigate caching\n\n```yaml\nproject_id: PROJ\nissue_type: research\n"
        "component: Platform\n```\n\nBody.\n"
    )
    path = tmp_path / "research.md"
    path.write_text(md, encoding="utf-8")

    item = build_create_plan(
        parse_markdown(path), story_points_field_id="customfield_12345"
    )[0]

    assert item["issueTypeName"] == "Research Spike"
