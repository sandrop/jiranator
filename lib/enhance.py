"""Deterministic helpers for the jiranator ``enhance`` path.

Ported from the legacy ``jirainator.enhance`` module. The pure helpers
(``parse_args``, ``find_todo_sections``, ``render_diff``, ``build_edit_payload``,
``is_stale_write``, ``KEY_RE``, ``EnhanceArgs``, ``EditFields``, ``TodoSection``)
land verbatim. The one real design change is ``select_template``: the legacy
hardcoded ``_TEMPLATES`` dict is replaced by reading a per-config, user-editable
``<issuetype>.md`` file from a templates dir (AC #4 -- config/profile-driven, not
hardcoded). ``enrich_description`` is the thin round-trip seam that restructures a
fetched issue's description against its issue-type template.

Imports are bare (``import models``) to match the plugin's ``lib/`` convention;
the templates dir is seeded by ``config.ensure_config_dir``.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NamedTuple, TypedDict

from models import IssueType

TODO_MARKER = "<!-- TODO"
# Canonical issue-key format. Single source of truth used by parse_args and
# re-exported for enhance_rest.
KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*-\d+$")

# Jira-side issue-type strings that map to a canonical IssueType. Keys are
# lowercased; values are the IssueType the string aliases to. Add an entry
# only when the org actually uses the variant (avoid speculation).
_ISSUE_TYPE_ALIASES: dict[str, IssueType] = {
    "research spike": IssueType.RESEARCH,
}


@dataclass(frozen=True)
class EnhanceArgs:
    issue_key: str
    interactive: bool
    push: bool


class EditFields(TypedDict):
    """Shape of the edit request body's ``fields`` payload: a single description
    field consumed by ``enhance_rest.update_issue_description``, which wraps it in
    ``{"fields": ...}`` and converts the markdown to ADF."""

    description: str


class TodoSection(NamedTuple):
    """A heading whose body contains a ``<!-- TODO -->`` marker."""

    heading: str
    line_number: int


def parse_args(argv: list[str]) -> EnhanceArgs:
    """Parse ``KEY [--interactive] [--push]``. KEY must come first; flags follow in any order.

    The first token MUST be the issue key (matching
    ``^[A-Z][A-Z0-9_]*-\\d+$``). Leading
    flags are rejected loud rather than silently treated as the key. Duplicate
    flags and unknown tokens both raise ``ValueError``.
    """
    if not argv:
        raise ValueError("issue key required")
    key = argv[0]
    if key.startswith("--"):
        raise ValueError(f"issue key must come first, got flag: {key}")
    if not KEY_RE.match(key):
        raise ValueError(f"invalid issue key: {key}")
    flags: set[str] = set()
    for token in argv[1:]:
        if token in ("--interactive", "--push"):
            if token in flags:
                raise ValueError(f"duplicate flag: {token}")
            flags.add(token)
        else:
            raise ValueError(f"unknown argument: {token}")
    return EnhanceArgs(
        issue_key=key,
        interactive="--interactive" in flags,
        push="--push" in flags,
    )


def _resolve_issue_type(issue_type: IssueType | str) -> IssueType:
    """Coerce an ``IssueType`` or string to the canonical ``IssueType``.

    Accepts the enum directly; otherwise lowercases the string, resolves aliases,
    then matches the enum. Any non-string / unknown value raises ``ValueError``.
    """
    if isinstance(issue_type, IssueType):
        return issue_type
    # Runtime defense: a caller may violate the declared type at runtime
    # (passing None, int, etc.); catch the AttributeError from `.lower()` and
    # re-raise as a clear ValueError matching the unknown-string path.
    try:
        lowered = issue_type.lower()
    except AttributeError as exc:
        raise ValueError(
            f"unsupported issue type: {issue_type!r} (expected IssueType or str)"
        ) from exc
    if lowered in _ISSUE_TYPE_ALIASES:
        return _ISSUE_TYPE_ALIASES[lowered]
    try:
        return IssueType(lowered)
    except ValueError as exc:
        raise ValueError(f"unsupported issue type: {issue_type}") from exc


def select_template(issue_type: IssueType | str, templates_dir: Path) -> str:
    """Return the markdown template body for ``issue_type`` (case-insensitive).

    Resolves the canonical ``IssueType`` (accepting an enum, a case-insensitive
    string, or a known alias), then reads ``templates_dir / "<value>.md"``. An
    unknown type or a missing template file both raise ``ValueError`` -- a known
    type with no seeded file is a broken install, not a silent empty template.
    """
    canonical = _resolve_issue_type(issue_type)
    path = Path(templates_dir) / f"{canonical.value}.md"
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(
            f"no template file for issue type {canonical.value!r} at {path}"
        ) from exc


def find_todo_sections(markdown: str) -> list[TodoSection]:
    """Return one TodoSection per ``### Heading`` whose body contains ``<!-- TODO``.

    Multiple TODO markers under the same heading collapse to one entry; TODOs
    before any heading are ignored.
    """
    results: list[TodoSection] = []
    current: TodoSection | None = None
    flagged = False
    for idx, line in enumerate(markdown.splitlines(), start=1):
        if line.startswith("### "):
            current = TodoSection(heading=line.rstrip(), line_number=idx)
            flagged = False
        elif TODO_MARKER in line and current is not None and not flagged:
            results.append(current)
            flagged = True
    return results


def render_diff(current: str, proposed: str, key: str) -> str:
    """Return a display-only unified diff with ``a/{key}`` vs ``b/{key}`` headers and 3 context lines.

    Headers carry the issue key for human-readable context; they are NOT real
    file paths and the output is not intended to be ``git apply``-able. Use only
    for terminal display, AskUserQuestion previews, or log output.
    """
    lines = difflib.unified_diff(
        current.splitlines(keepends=True),
        proposed.splitlines(keepends=True),
        fromfile=f"a/{key}",
        tofile=f"b/{key}",
        n=3,
    )
    return "".join(lines)


def build_edit_payload(description_markdown: str) -> EditFields:
    """Return the ``fields`` payload for the edit request body.

    The REST helper wraps this in ``{"fields": ...}`` and converts the markdown
    to ADF. ``description`` MUST use real newlines, not ``\\n`` escapes.
    """
    if not description_markdown.strip():
        raise ValueError("description required")
    return EditFields(description=description_markdown)


def enrich_description(fetched_issue: dict[str, Any], templates_dir: Path) -> str:
    """Restructure a fetched issue's description against its issue-type template.

    Reads the issue type from ``fetched_issue["fields"]["issuetype"]["name"]`` and
    returns the matching template skeleton. Phase 1 folds in the empty-description
    path (the template is the restructured starting point the push path then
    converts to ADF); a content-merge remap is future work. Raises ``ValueError``
    when the issue type is missing or unknown (via ``select_template``).
    """
    fields = fetched_issue.get("fields") or {}
    issuetype = (fields.get("issuetype") or {}).get("name") or ""
    return select_template(issuetype, templates_dir)


def _normalize_for_compare(text: str) -> str:
    """Per-line rstrip plus trailing-blank-line strip."""
    lines = [line.rstrip() for line in text.splitlines()]
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def is_stale_write(initial_description: str, prepush_description: str) -> bool:
    """Return True iff the two descriptions differ (normalized: rstrip per line)."""
    return _normalize_for_compare(initial_description) != _normalize_for_compare(
        prepush_description
    )
