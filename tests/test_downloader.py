"""Unit tests for the unified downloader's pure logic.

Transition extraction, record assembly, paginated fetch, and the changelog
truncation top-up. All transport is a hand-injected fake; no network.
"""

import downloader


def _issue_with_status_change():
    return {
        "key": "GDP-1",
        "fields": {"summary": "S", "issuetype": {"name": "Story"}},
        "changelog": {
            "histories": [
                {
                    "author": {"displayName": "Jane", "accountId": "557:abc"},
                    "created": "2026-06-14T17:44:00.000+0200",
                    "items": [
                        {
                            "field": "status",
                            "fromString": "In Progress",
                            "toString": "Done",
                        }
                    ],
                }
            ]
        },
    }


def _issue_with_sprint_change():
    return {
        "key": "GDP-2",
        "fields": {"summary": "T", "issuetype": {"name": "Task"}},
        "changelog": {
            "histories": [
                {
                    "author": {"displayName": "Amir", "accountId": "557:def"},
                    "created": "2026-06-15T09:00:00.000+0200",
                    "items": [
                        {
                            "field": "Sprint",
                            "fromString": "Sprint 1",
                            "toString": "Sprint 2",
                        }
                    ],
                }
            ]
        },
    }


class FakeHttp:
    """Records request bodies; serves scripted response pages in order."""

    def __init__(self, pages, changelog_values=None):
        self.pages = list(pages)
        self.bodies = []
        self.changelog_values = changelog_values or {}
        self.changelog_calls = []

    def post_json(self, path, body):
        self.bodies.append(body)
        return self.pages.pop(0)

    def get_json(self, path, params=None):
        # Model a single-page changelog GET: real Jira reports `total` and
        # `isLast`, so the top-up loop stops on the response metadata.
        self.changelog_calls.append((path, params))
        values = self.changelog_values.get(path, [])
        return {"values": values, "total": len(values), "isLast": True}


def test_extract_status_transitions_yields_one_row_per_status_item():
    (row,) = downloader.extract_status_transitions(_issue_with_status_change())
    assert row == {
        "issue_key": "GDP-1",
        "issue_type": "Story",
        "summary": "S",
        "from_status": "In Progress",
        "to_status": "Done",
        "transitioned_at": "2026-06-14T17:44:00.000+0200",
        "author": "Jane",
        "author_id": "557:abc",
    }


def test_extract_status_transitions_ignores_non_status_items():
    issue = _issue_with_sprint_change()
    assert downloader.extract_status_transitions(issue) == []


def test_extract_sprint_transitions_yields_one_row_per_sprint_item():
    (row,) = downloader.extract_sprint_transitions(_issue_with_sprint_change())
    assert row == {
        "issue_key": "GDP-2",
        "before_names": "Sprint 1",
        "after_names": "Sprint 2",
        "changed_at": "2026-06-15T09:00:00.000+0200",
        "author": "Amir",
        "author_id": "557:def",
    }
    assert list(row.keys()) == downloader.SPRINT_TRANSITION_FIELDNAMES


def test_build_record_keeps_raw_fields_and_inlines_transitions():
    issue = _issue_with_status_change()
    issue.update({"id": "101", "self": "https://x/rest/api/3/issue/101"})
    rec = downloader.build_record(issue)
    assert rec["id"] == "101" and rec["key"] == "GDP-1" and rec["self"].endswith("/101")
    assert rec["fields"] is issue["fields"] and rec["changelog"] is issue["changelog"]
    assert rec["status_transitions"] == downloader.extract_status_transitions(issue)
    assert rec["sprint_transitions"] == downloader.extract_sprint_transitions(issue)
    assert set(rec) == {
        "id",
        "key",
        "self",
        "fields",
        "changelog",
        "status_transitions",
        "sprint_transitions",
    }


def test_fetch_issues_follows_next_page_token():
    fake = FakeHttp(
        [
            {
                "issues": [{"key": "A", "changelog": {"histories": []}}],
                "isLast": False,
                "nextPageToken": "t2",
            },
            {
                "issues": [{"key": "B", "changelog": {"histories": []}}],
                "isLast": True,
                "nextPageToken": None,
            },
        ]
    )
    issues = downloader.fetch_issues(fake, "project = GDP")
    assert [i["key"] for i in issues] == ["A", "B"]
    assert fake.bodies[0]["jql"] == "project = GDP"
    assert fake.bodies[0]["maxResults"] == 100
    assert fake.bodies[0]["expand"] == "changelog"
    assert fake.bodies[1]["nextPageToken"] == "t2"


def test_fetch_issues_paginates_when_islast_absent():
    # A token-based search response may carry nextPageToken without isLast:
    # pagination must continue while a token is present, not stop after page 1.
    fake = FakeHttp(
        [
            {
                "issues": [{"key": "A", "changelog": {"histories": []}}],
                "nextPageToken": "t2",
            },
            {
                "issues": [{"key": "B", "changelog": {"histories": []}}],
                "nextPageToken": None,
            },
        ]
    )
    issues = downloader.fetch_issues(fake, "project = GDP")
    assert [i["key"] for i in issues] == ["A", "B"]
    assert fake.bodies[1]["nextPageToken"] == "t2"


def test_fetch_issues_tops_up_truncated_changelog():
    path = "/rest/api/3/issue/A/changelog"
    full = [
        {"id": "1", "items": [{"field": "status"}]},
        {"id": "2", "items": [{"field": "status"}]},
    ]
    fake = FakeHttp(
        [
            {
                "issues": [
                    {"key": "A", "changelog": {"total": 2, "histories": [full[0]]}}
                ],
                "isLast": True,
                "nextPageToken": None,
            }
        ],
        changelog_values={path: full},
    )
    (issue,) = downloader.fetch_issues(fake, "project = GDP")
    assert issue["changelog"]["histories"] == full
    assert fake.changelog_calls and fake.changelog_calls[0][0] == path


def test_fetch_issues_refetches_changelog_when_total_absent():
    # A non-empty expanded changelog with NO `total` may itself be truncated;
    # trusting the inline count would silently drop older histories. The full
    # changelog must be refetched.
    path = "/rest/api/3/issue/A/changelog"
    full = [
        {"id": "1", "items": [{"field": "status"}]},
        {"id": "2", "items": [{"field": "status"}]},
    ]
    fake = FakeHttp(
        [
            {
                "issues": [{"key": "A", "changelog": {"histories": [full[0]]}}],
                "isLast": True,
                "nextPageToken": None,
            }
        ],
        changelog_values={path: full},
    )
    (issue,) = downloader.fetch_issues(fake, "project = GDP")
    assert issue["changelog"]["histories"] == full
    assert fake.changelog_calls and fake.changelog_calls[0][0] == path


def test_fetch_issues_pages_changelog_past_short_pages():
    # A server-side cap can return fewer than requested while `total` still
    # indicates more histories. The top-up must keep paging to the total rather
    # than stopping on the first short page.
    full = [{"id": str(i), "items": [{"field": "status"}]} for i in range(5)]

    class PagingHttp:
        def __init__(self):
            self.changelog_calls = []

        def post_json(self, p, body):
            return {
                "issues": [
                    {"key": "A", "changelog": {"total": 5, "histories": [full[0]]}}
                ],
                "isLast": True,
                "nextPageToken": None,
            }

        def get_json(self, p, params=None):
            self.changelog_calls.append(params)
            start = params["startAt"]
            # Serve two-at-a-time, well under the 100 requested, total 5.
            chunk = full[start : start + 2]
            return {"values": chunk, "total": 5, "isLast": start + len(chunk) >= 5}

    fake = PagingHttp()
    (issue,) = downloader.fetch_issues(fake, "project = GDP")
    assert issue["changelog"]["histories"] == full
    assert [p["startAt"] for p in fake.changelog_calls] == [0, 2, 4]


def test_fetch_issues_skips_refetch_for_empty_changelog():
    # An empty changelog with no `total` is not truncated: no refetch.
    fake = FakeHttp(
        [
            {
                "issues": [{"key": "A", "changelog": {"histories": []}}],
                "isLast": True,
                "nextPageToken": None,
            }
        ]
    )
    (issue,) = downloader.fetch_issues(fake, "project = GDP")
    assert issue["changelog"]["histories"] == []
    assert fake.changelog_calls == []
