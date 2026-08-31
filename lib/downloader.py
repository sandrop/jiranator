"""Unified jiranator issue downloader.

The single reconciled downloader on the unified JSON schema, replacing the two
prior downloaders. It is JQL-driven (user-supplied, no hardcoded filter-ID
presets) and emits the unified JSON record: raw ``fields`` + ``changelog`` kept
verbatim (downloader B's lossless capture) plus inline ``status_transitions`` /
``sprint_transitions`` (downloader A's changelog extraction). A top-level
``meta`` stamp records ``{snapshot_at, labels, jql, schema_version}``.

Transport goes through an injected :class:`~jira_http.HttpTransport`
(``post_json`` / ``get_json``): production wires a ``JiraHttp`` (stdlib urllib +
basic auth), tests inject a fake and never hit the network. Persistence is
delegated to :mod:`store` (``.tmp`` + ``os.replace`` staging + ``download.complete``
sentinel).

Unified record keys: ``id, key, self, fields, changelog, status_transitions,
sprint_transitions``. ``meta`` keys: ``snapshot_at, labels, jql, schema_version``.

``STATUS_TRANSITION_FIELDNAMES`` / ``SPRINT_TRANSITION_FIELDNAMES`` are copied
verbatim from downloader A. The unified schema itself is documented in the
project's recon deliverable.

Signatures:
    extract_status_transitions(issue) -> list[dict]
    extract_sprint_transitions(issue) -> list[dict]
    build_record(issue) -> dict
    fetch_issues(http, jql, fields=None) -> list[dict]
    download(http, jql, out_dir, labels=(), schema_version="1.0", now=None) -> DownloadResult
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

import store

if TYPE_CHECKING:
    # Annotation-only: `from __future__ import annotations` keeps these lazy, so
    # the downloader keeps its runtime dependency on the duck-typed transport
    # surface only, without importing jira_http at load time.
    from jira_http import HttpTransport

# Copied verbatim from downloader A (jira_batch_downloader.py).
SPRINT_TRANSITION_FIELDNAMES = [
    "issue_key",
    "before_names",
    "after_names",
    "changed_at",
    "author",
    "author_id",
]

STATUS_TRANSITION_FIELDNAMES = [
    "issue_key",
    "issue_type",
    "summary",
    "from_status",
    "to_status",
    "transitioned_at",
    "author",
    "author_id",
]


class DownloadResult(NamedTuple):
    """Paths and count returned by :func:`download`."""

    issues_path: str
    meta_path: str
    count: int


_PAGE_SIZE = 100
_CHANGELOG_PAGE = 100


def _issue_type(issue: dict) -> str:
    issuetype = issue.get("fields", {}).get("issuetype")
    return issuetype.get("name", "") if isinstance(issuetype, dict) else ""


def extract_status_transitions(issue: dict) -> list[dict]:
    """One row per ``status`` changelog item (ported verbatim from downloader A)."""
    key = issue.get("key", "")
    issue_type = _issue_type(issue)
    summary = issue.get("fields", {}).get("summary", "")
    rows: list[dict] = []
    for history in issue.get("changelog", {}).get("histories", []):
        author_obj = history.get("author", {})
        author = author_obj.get("displayName", "")
        author_id = author_obj.get("accountId", "")
        created = history.get("created", "")
        for item in history.get("items", []):
            if item.get("field") != "status":
                continue
            rows.append(
                {
                    "issue_key": key,
                    "issue_type": issue_type,
                    "summary": summary,
                    "from_status": item.get("fromString", ""),
                    "to_status": item.get("toString", ""),
                    "transitioned_at": created,
                    "author": author,
                    "author_id": author_id,
                }
            )
    return rows


def extract_sprint_transitions(issue: dict) -> list[dict]:
    """One row per ``Sprint`` changelog item (ported verbatim from downloader A).

    ``before_names`` / ``after_names`` are the verbatim ``fromString`` /
    ``toString`` values (raw multi-sprint strings, not pre-split).
    """
    key = issue.get("key", "")
    rows: list[dict] = []
    for history in issue.get("changelog", {}).get("histories", []):
        author_obj = history.get("author", {})
        author = author_obj.get("displayName", "")
        author_id = author_obj.get("accountId", "")
        created = history.get("created", "")
        for item in history.get("items", []):
            if item.get("field") != "Sprint":
                continue
            rows.append(
                {
                    "issue_key": key,
                    "before_names": item.get("fromString", ""),
                    "after_names": item.get("toString", ""),
                    "changed_at": created,
                    "author": author,
                    "author_id": author_id,
                }
            )
    return rows


def build_record(issue: dict) -> dict:
    """Assemble the unified 7-key record; raw ``fields``/``changelog`` verbatim."""
    return {
        "id": issue.get("id", ""),
        "key": issue.get("key", ""),
        "self": issue.get("self", ""),
        "fields": issue.get("fields", {}),
        "changelog": issue.get("changelog", {}),
        "status_transitions": extract_status_transitions(issue),
        "sprint_transitions": extract_sprint_transitions(issue),
    }


def _fetch_full_changelog(
    http: HttpTransport, issue_key: str, total: int | None = None
) -> list[dict]:
    """Page the full changelog when the search result truncated histories.

    ``total=None`` means the search response did not report a changelog total, so
    the true length is unknown: page until a short or empty page is returned
    rather than trusting the possibly-truncated inline count.
    """
    histories: list[dict] = []
    start_at = 0
    while True:
        data = http.get_json(
            f"/rest/api/3/issue/{issue_key}/changelog",
            {"startAt": start_at, "maxResults": _CHANGELOG_PAGE},
        )
        values = data.get("values", [])
        histories.extend(values)
        start_at += len(values)
        if not values or data.get("isLast") is True:
            break
        # The changelog GET reports its own authoritative total; fall back to
        # the search-provided total. Stop when we have reached it. Never stop on
        # a short page alone: a server-side page cap can return fewer than
        # requested while more histories remain.
        resp_total = data.get("total", total)
        if resp_total is not None and start_at >= resp_total:
            break
        # No total and no isLast signal: a short page is the only remaining
        # indication that the changelog is exhausted.
        if resp_total is None and len(values) < _CHANGELOG_PAGE:
            break
    return histories


def fetch_issues(
    http: HttpTransport, jql: str, fields: Iterable[str] | None = None
) -> list[dict]:
    """Paginate ``POST /rest/api/3/search/jql`` over the injected transport.

    ``fields=None`` requests ``["*all"]`` (downloader B's lossless choice) so no
    per-field curation is baked in. On truncated changelogs the full history is
    topped up via ``GET /rest/api/3/issue/{key}/changelog``.
    """
    requested_fields = list(fields) if fields is not None else ["*all"]
    all_issues: list[dict] = []
    next_page_token = None
    while True:
        body: dict = {
            "jql": jql,
            "maxResults": _PAGE_SIZE,
            "fields": requested_fields,
            "expand": "changelog",
        }
        if next_page_token is not None:
            body["nextPageToken"] = next_page_token
        data = http.post_json("/rest/api/3/search/jql", body)
        issues = data.get("issues", [])
        all_issues.extend(issues)
        next_page_token = data.get("nextPageToken")
        # The token-based search response may carry a nextPageToken without an
        # isLast field, so do not default a missing isLast to True: keep paging
        # while a token is present and only stop on an explicit isLast, an empty
        # page, or an absent token.
        if data.get("isLast") is True or not issues or not next_page_token:
            break

    for issue in all_issues:
        changelog = issue.get("changelog", {})
        histories = changelog.get("histories", [])
        total = changelog.get("total")
        # Refetch when the reported total exceeds the inline count (known
        # truncation) OR when total is absent on a non-empty changelog: an
        # unknown total may itself signal truncation, so page the full history
        # rather than silently dropping older entries and their transitions.
        if (total is not None and len(histories) < total) or (
            total is None and histories
        ):
            issue["changelog"]["histories"] = _fetch_full_changelog(
                http, issue["key"], total
            )
    return all_issues


def download(
    http: HttpTransport,
    jql: str,
    out_dir: str | Path,
    labels: Iterable[str] = (),
    schema_version: str = "1.0",
    now: datetime | None = None,
) -> DownloadResult:
    """Fetch, assemble unified records, and persist an atomic snapshot."""
    out_dir = Path(out_dir)
    issues = fetch_issues(http, jql)
    records = [build_record(issue) for issue in issues]
    snapshot_at = (now or datetime.now()).isoformat()
    meta = {
        "snapshot_at": snapshot_at,
        "labels": list(labels),
        "jql": jql,
        "schema_version": schema_version,
    }
    issues_path, meta_path = store.write_snapshot(records, meta, out_dir)
    return DownloadResult(
        issues_path=str(issues_path),
        meta_path=str(meta_path),
        count=len(records),
    )
