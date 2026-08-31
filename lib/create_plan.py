"""Build the Atlassian MCP ``createJiraIssue`` parameter plan.

Turns a parsed ``MarkdownParseResult`` into one preview-only parameter dict per
ticket, shaped for the MCP ``createJiraIssue`` tool. This module is pure and
network-free: the ``cloudId`` and the call loop itself live in the
``/jiranator:create`` slash command, which injects ``cloudId`` at call time and
paces the writes. Empty optionals are omitted so the plan carries only what each
issue actually sets.
"""

from __future__ import annotations

from typing import Any

from markdown_parser import MarkdownParseResult, MarkdownTicket
from models import IssueType

_ISSUE_TYPE_NAMES = {IssueType.RESEARCH: "Research Spike"}


def build_create_plan(
    result: MarkdownParseResult, *, story_points_field_id: str
) -> list[dict[str, Any]]:
    """Return one ``createJiraIssue``-shaped param dict per parsed ticket.

    The ``additional_fields`` map always carries ``components`` and adds the
    configured story-points field only when set, then merges nonempty unknown
    ``extra_fields``. ``parent`` is a top-level MCP argument when set. No
    ``cloudId`` is included; the command injects it at call time.
    """
    if not story_points_field_id and any(
        ticket.story_points is not None for ticket in result.tickets
    ):
        raise ValueError("field_ids.story_points is required for tickets with points")
    return [_plan_item(ticket, story_points_field_id) for ticket in result.tickets]


def _plan_item(ticket: MarkdownTicket, story_points_field_id: str) -> dict[str, Any]:
    reserved_fields = {"components", "parent", story_points_field_id}
    collisions = sorted(reserved_fields & ticket.extra_fields.keys())
    if collisions:
        raise ValueError(
            f"extra fields may not override reserved field(s): {', '.join(collisions)}"
        )

    additional_fields: dict[str, Any] = {
        "components": [{"name": ticket.component}],
    }
    if ticket.story_points is not None:
        additional_fields[story_points_field_id] = ticket.story_points
    additional_fields.update(
        {key: value for key, value in ticket.extra_fields.items() if value is not None}
    )

    item = {
        "projectKey": ticket.project_id,
        "issueTypeName": _ISSUE_TYPE_NAMES.get(
            ticket.issue_type, ticket.issue_type.value.capitalize()
        ),
        "summary": ticket.summary,
        "description": ticket.description,
        "additional_fields": additional_fields,
    }
    if ticket.epic_key:
        item["parent"] = ticket.epic_key
    return item
