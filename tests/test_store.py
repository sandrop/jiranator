"""Persistence tests for the downloader's atomic snapshot.

Drives ``downloader.download`` through a fake transport and asserts on the real
files written to a tmp dir: JSONL round-trip, meta shape, sentinel, no leftover
``.tmp``. Also pins the user-supplied-JQL / no-preset contract.
"""

import json
import os
import stat
from datetime import datetime
from pathlib import Path

import downloader
import pytest


class FakeHttp:
    def __init__(self, pages):
        self.pages = list(pages)

    def post_json(self, path, body):
        return self.pages.pop(0)

    def get_json(self, path, params=None):
        return {"values": []}


def _one_issue_page():
    return [
        {
            "issues": [
                {
                    "id": "101",
                    "key": "GDP-1",
                    "self": "https://x/rest/api/3/issue/101",
                    "fields": {"summary": "S", "issuetype": {"name": "Story"}},
                    "changelog": {
                        "total": 1,
                        "histories": [
                            {
                                "author": {
                                    "displayName": "Jane",
                                    "accountId": "557:abc",
                                },
                                "created": "2026-06-14T17:44:00.000+0200",
                                "items": [
                                    {
                                        "field": "status",
                                        "fromString": "To Do",
                                        "toString": "Done",
                                    }
                                ],
                            }
                        ],
                    },
                }
            ],
            "isLast": True,
            "nextPageToken": None,
        }
    ]


def test_download_writes_jsonl_meta_and_sentinel(tmp_path):
    fixed = datetime(2026, 8, 24, 21, 30, 0)
    result = downloader.download(
        FakeHttp(_one_issue_page()),
        "project = GDP",
        out_dir=tmp_path,
        labels=["gdp"],
        now=fixed,
    )

    issues_lines = (tmp_path / "issues.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(issues_lines) == 1
    record = json.loads(issues_lines[0])
    assert record["key"] == "GDP-1"
    assert record["status_transitions"][0]["to_status"] == "Done"

    meta = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    assert set(meta) == {"snapshot_at", "labels", "jql", "schema_version"}
    assert meta["jql"] == "project = GDP"
    assert meta["labels"] == ["gdp"]
    assert meta["snapshot_at"] == fixed.isoformat()

    assert (tmp_path / "download.complete").exists()
    assert list(tmp_path.glob("*.tmp")) == []

    assert result.count == 1
    assert Path(result.issues_path) == tmp_path / "issues.jsonl"
    assert Path(result.meta_path) == tmp_path / "meta.json"


def test_meta_records_user_supplied_jql(tmp_path):
    downloader.download(
        FakeHttp([{"issues": [], "isLast": True, "nextPageToken": None}]),
        "assignee = currentUser()",
        out_dir=tmp_path,
    )
    meta = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    assert meta["jql"] == "assignee = currentUser()"


def test_no_hardcoded_filter_presets_in_downloader():
    src = (Path(__file__).resolve().parent.parent / "lib" / "downloader.py").read_text(
        encoding="utf-8"
    )
    for preset in ("57756", "58131", "58065", "54786", "filter = "):
        assert preset not in src


def test_failed_second_replace_leaves_no_completion_sentinel(tmp_path, monkeypatch):
    # A prior download completes and stamps the sentinel.
    downloader.download(FakeHttp(_one_issue_page()), "project = A", out_dir=tmp_path)
    assert (tmp_path / "download.complete").exists()

    # A repeat download whose SECOND os.replace (meta.json) fails must not leave
    # the old sentinel certifying the mixed new-issues / old-meta state.
    real_replace = os.replace
    calls = {"n": 0}

    def flaky_replace(src, dst):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("simulated failure replacing meta.json")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", flaky_replace)
    with pytest.raises(OSError):
        downloader.download(
            FakeHttp(_one_issue_page()), "project = B", out_dir=tmp_path
        )

    assert not (tmp_path / "download.complete").exists()
    assert list(tmp_path.glob("*.tmp")) == []


def test_snapshot_is_owner_only(tmp_path):
    out_dir = tmp_path / "snap"  # not pre-existing, so the dir mode is enforced
    downloader.download(FakeHttp(_one_issue_page()), "project = A", out_dir=out_dir)
    for name in ("issues.jsonl", "meta.json"):
        mode = stat.S_IMODE((out_dir / name).stat().st_mode)
        assert mode == 0o600, f"{name} mode is {oct(mode)}"
    assert stat.S_IMODE(out_dir.stat().st_mode) == 0o700
