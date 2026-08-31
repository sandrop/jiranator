"""Round-trip test (AC #3): download -> enrich -> update over a fake transport.

A fetched issue with an empty description is restructured against its issue-type
template and PUT back as ADF, with no network in the loop. Pins that the pushed
body reflects the template headings and that ``is_stale_write`` catches a
baseline that changed under the enrich step.
"""

import pytest

import enhance
import enhance_rest
from models import IssueType


class FakeHttp:
    def __init__(self, issue):
        self._issue = issue
        self.puts = []

    def get_json(self, path, params=None):
        return self._issue

    def post_json(self, path, body):
        raise AssertionError("unused")

    def put_json(self, path, body):
        self.puts.append((path, body))


def _seed_story(tmp_path):
    (tmp_path / "story.md").write_text(
        "### Description\n<!-- TODO: Add description -->\n\n"
        "### Acceptance Criteria\n<!-- TODO: Define acceptance criteria -->\n",
        encoding="utf-8",
    )
    return tmp_path


def _fill_todos(skeleton: str) -> str:
    """Replace each ``<!-- TODO: ... -->`` marker line with real content so the
    filled description converts to clean ADF (the push guard refuses any leftover
    HTML-comment markers). Stands in for the human/enrich fill step."""
    out = []
    for line in skeleton.splitlines():
        if enhance.TODO_MARKER in line:
            out.append("filled in.")
        else:
            out.append(line)
    return "\n".join(out) + "\n"


def test_download_enrich_update_round_trip(tmp_path):
    _seed_story(tmp_path)
    issue = {
        "key": "PROJ-1",
        "fields": {"issuetype": {"name": "Story"}, "description": None},
    }
    http = FakeHttp(issue)

    fetched = enhance_rest.fetch_issue(http, "PROJ-1")
    restructured = enhance.enrich_description(fetched, tmp_path)

    # The empty-description path surfaces every template section as a TODO,
    # proving the fetched issue was restructured against its issue-type template.
    todos = enhance.find_todo_sections(restructured)
    assert [s.heading for s in todos] == ["### Description", "### Acceptance Criteria"]

    filled = _fill_todos(restructured)
    enhance_rest.update_issue_description(http, "PROJ-1", filled)
    path, body = http.puts[0]
    assert path == "/rest/api/3/issue/PROJ-1"
    headings = [
        node["content"][0]["text"]
        for node in body["fields"]["description"]["content"]
        if node["type"] == "heading"
    ]
    assert headings == ["Description", "Acceptance Criteria"]


def test_push_of_unfilled_skeleton_is_refused(tmp_path):
    # The fail-loud backstop: a template still carrying <!-- TODO --> markers is
    # a degraded ADF conversion, so update refuses it before any PUT.
    _seed_story(tmp_path)
    issue = {"key": "PROJ-1", "fields": {"issuetype": {"name": "Story"}}}
    http = FakeHttp(issue)
    skeleton = enhance.enrich_description(issue, tmp_path)

    with pytest.raises(ValueError, match="refusing to push"):
        enhance_rest.update_issue_description(http, "PROJ-1", skeleton)
    assert http.puts == []


def test_enrich_changes_the_baseline(tmp_path):
    _seed_story(tmp_path)
    issue = {
        "key": "PROJ-1",
        "fields": {"issuetype": {"name": "story"}, "description": ""},
    }
    restructured = enhance.enrich_description(issue, tmp_path)
    assert enhance.is_stale_write("", restructured) is True


def test_enrich_selects_by_issue_type(tmp_path):
    (tmp_path / "bug.md").write_text("### Steps to Reproduce\n", encoding="utf-8")
    issue = {"fields": {"issuetype": {"name": "Bug"}}}
    assert enhance.enrich_description(issue, tmp_path) == enhance.select_template(
        IssueType.BUG, tmp_path
    )
