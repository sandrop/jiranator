"""Stdlib data types shared by the jiranator enricher and creator paths.

The legacy ``jirainator.models`` imports ``pydantic``; the plugin is zero-install
stdlib-only, so the plain ``str`` Enums ``IssueType`` and ``LinkType`` are ported
here. The ``MarkdownTicket`` / ``MarkdownParseResult`` shapes live in
``markdown_parser`` as stdlib dataclasses (the creator path). Enum values are
lowercase strings because ``enhance.select_template`` and the alias table
lowercase before matching.
"""

from __future__ import annotations

from enum import Enum


class IssueType(str, Enum):
    """Supported Jira issue types (canonical, lowercase values)."""

    EPIC = "epic"
    STORY = "story"
    TASK = "task"
    RESEARCH = "research"
    BUG = "bug"


class LinkType(str, Enum):
    """Supported issue-link types (canonical, lowercase values)."""

    BLOCKS = "blocks"
    DEPENDS_ON = "depends_on"
    RELATES_TO = "relates_to"
