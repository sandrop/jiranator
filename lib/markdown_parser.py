"""Markdown parser for the jiranator creator path (stdlib port).

Ported from the standalone ``jirainator.markdown_parser``. The legacy module
depends on ``pydantic`` and ``pyyaml``; the plugin is zero-install
stdlib-only, so the ``MarkdownTicket`` / ``MarkdownParseResult`` shapes are
``@dataclass``es and the flat ``key: value`` YAML metadata block is read by a
small local parser (``_parse_yaml_block``) that mirrors ``yaml.safe_load`` for
the shapes we emit: scalar values, empty value -> ``None``. The split/validate
logic, the field sets, and the regexes are carried over verbatim.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from models import IssueType, LinkType


class MarkdownParseError(Exception):
    """Error during markdown parsing, carrying per-block messages."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__(f"Markdown parsing failed with {len(errors)} error(s)")


@dataclass
class MarkdownTicket:
    """Parsed ticket from markdown input."""

    project_id: str
    issue_type: IssueType
    summary: str  # From H2 header
    component: str
    description: str  # Content after YAML block
    epic_key: str | None = None
    story_points: int | None = None
    link_to: str | None = None
    link_type: LinkType | None = None
    extra_fields: dict[str, Any] = field(default_factory=dict)
    line_number: int = 0


@dataclass
class MarkdownParseResult:
    """Result from parsing a markdown file."""

    source_file: str
    tickets: list[MarkdownTicket]
    warnings: list[str] = field(default_factory=list)


# Required YAML fields for all issue types
REQUIRED_FIELDS = {"project_id", "issue_type", "component"}

# Optional YAML fields with known semantics
OPTIONAL_FIELDS = {"epic_key", "story_points", "link_to", "link_type"}

# Fields that are excluded for epics
EPIC_EXCLUDED_FIELDS = {"epic_key", "story_points"}

# Pattern for ticket block delimiter
BLOCK_DELIMITER = re.compile(r"^---\s*$", re.MULTILINE)

# Pattern for H2 header (summary)
H2_PATTERN = re.compile(r"^##\s+(.+)$", re.MULTILINE)

# Pattern for YAML code block
YAML_BLOCK_PATTERN = re.compile(r"```ya?ml\s*\n(.*?)\n```", re.DOTALL)

# Jira project keys start with a letter and may then contain letters, digits,
# or underscores before the numeric issue suffix.
TICKET_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*-\d+$")

# Comment marker inside a YAML metadata block
_COMMENT = "#"


class _YamlBlockError(Exception):
    """Raised for a malformed flat YAML metadata block."""


def _strip_comment(line: str) -> str:
    quote: str | None = None
    escaped = False
    for index, char in enumerate(line):
        if escaped:
            escaped = False
        elif quote == '"' and char == "\\":
            escaped = True
        elif quote:
            if char == quote:
                quote = None
        elif char in ("'", '"'):
            quote = char
        elif char == _COMMENT and (index == 0 or line[index - 1].isspace()):
            return line[:index]
    return line


def _parse_scalar(value: str) -> str:
    if value.startswith('"'):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as error:
            raise _YamlBlockError(f"invalid quoted scalar: {value!r}") from error
        if not isinstance(parsed, str):
            raise _YamlBlockError(f"scalar value must be text: {value!r}")
        return parsed
    if value.startswith("'"):
        if not value.endswith("'") or len(value) < 2:
            raise _YamlBlockError(f"invalid quoted scalar: {value!r}")
        return value[1:-1].replace("''", "'")
    return value


def _parse_yaml_block(text: str) -> dict[str, Any]:
    """Parse a flat ``key: value`` YAML metadata block with stdlib only.

    Mirrors ``yaml.safe_load`` for the shapes the creator emits: top-level
    scalar entries, an empty value (``key:``) reads as ``None`` so a blank
    optional is treated as absent rather than an empty string. Nested
    structures and lists are unsupported and raise ``_YamlBlockError``.
    """
    metadata: dict[str, Any] = {}
    for raw_line in text.splitlines():
        line = _strip_comment(raw_line).rstrip()
        if not line.strip():
            continue
        if line[0].isspace():
            raise _YamlBlockError(f"unexpected indentation: {raw_line!r}")
        stripped = line.strip()
        if stripped.startswith("- "):
            raise _YamlBlockError(f"unexpected list item: {raw_line!r}")
        key, separator, value = stripped.partition(":")
        key = key.strip()
        if not separator or not key or any(char.isspace() for char in key):
            raise _YamlBlockError(f"malformed entry: {raw_line!r}")
        value = value.strip()
        metadata[key] = _parse_scalar(value) if value else None
    return metadata


def parse_markdown(file_path: Path) -> MarkdownParseResult:
    """Parse a markdown file and return validated MarkdownTicket objects.

    Args:
        file_path: Path to the markdown file.

    Returns:
        MarkdownParseResult with parsed tickets and warnings.

    Raises:
        MarkdownParseError: If validation fails with list of error messages.
        FileNotFoundError: If file doesn't exist.
    """
    if not file_path.exists():
        raise FileNotFoundError(f"Markdown file not found: {file_path}")

    content = file_path.read_text(encoding="utf-8")

    if not content.strip():
        raise MarkdownParseError(["Markdown file is empty"])

    errors: list[str] = []
    warnings: list[str] = []
    tickets: list[MarkdownTicket] = []

    # Split content into ticket blocks
    blocks = _split_into_ticket_blocks(content)

    if not blocks:
        raise MarkdownParseError(
            ["No ticket blocks found. Use '---' to delimit tickets."]
        )

    for block_num, (block_content, line_number) in enumerate(blocks, start=1):
        block_errors, block_warnings, ticket = _parse_ticket_block(
            block_num, block_content, line_number
        )
        errors.extend(block_errors)
        warnings.extend(block_warnings)
        if ticket:
            tickets.append(ticket)

    if errors:
        raise MarkdownParseError(errors)

    return MarkdownParseResult(
        source_file=str(file_path),
        tickets=tickets,
        warnings=warnings,
    )


def _split_into_ticket_blocks(content: str) -> list[tuple[str, int]]:
    """Split content by '---' delimiter and return blocks with line numbers.

    Args:
        content: Full markdown content.

    Returns:
        List of (block_content, starting_line_number) tuples.
    """
    lines = content.split("\n")
    blocks: list[tuple[str, int]] = []
    current_block_lines: list[str] = []
    current_start_line = 1

    for i, line in enumerate(lines, start=1):
        candidate_lines: list[str] = []
        for candidate in lines[i:]:
            if BLOCK_DELIMITER.match(candidate):
                break
            candidate_lines.append(candidate)
        next_nonempty = next(
            (candidate for candidate in candidate_lines if candidate.strip()), None
        )
        starts_next_ticket = bool(
            next_nonempty
            and H2_PATTERN.fullmatch(next_nonempty)
            and YAML_BLOCK_PATTERN.search("\n".join(candidate_lines))
        )
        if BLOCK_DELIMITER.match(line) and starts_next_ticket:
            # If we have accumulated content, save it as a block
            if current_block_lines:
                block_content = "\n".join(current_block_lines).strip()
                if block_content:
                    blocks.append((block_content, current_start_line))
            # Start a new block
            current_block_lines = []
            current_start_line = i + 1
        else:
            if not current_block_lines and not line.strip():
                # Skip leading empty lines, adjust start line
                current_start_line = i + 1
            else:
                current_block_lines.append(line)

    # Don't forget the last block
    if current_block_lines:
        block_content = "\n".join(current_block_lines).strip()
        if block_content:
            blocks.append((block_content, current_start_line))

    return blocks


def _parse_ticket_block(
    block_num: int, content: str, line_number: int
) -> tuple[list[str], list[str], MarkdownTicket | None]:
    """Parse a single ticket block.

    Args:
        block_num: 1-based block number for error messages.
        content: Block content.
        line_number: Starting line number in original file.

    Returns:
        Tuple of (errors, warnings, ticket or None).
    """
    errors: list[str] = []
    warnings: list[str] = []

    # Extract H2 header (summary)
    h2_match = H2_PATTERN.search(content)
    if not h2_match:
        errors.append(
            f"Block {block_num} (line {line_number}): Missing H2 header for summary"
        )
        return errors, warnings, None

    summary = h2_match.group(1).strip()

    # Extract YAML metadata block
    yaml_match = YAML_BLOCK_PATTERN.search(content)
    if not yaml_match:
        errors.append(
            f"Block {block_num} (line {line_number}): Missing YAML metadata block. "
            "Use ```yaml ... ``` to define ticket metadata."
        )
        return errors, warnings, None

    yaml_content = yaml_match.group(1)

    # Parse the flat YAML metadata block
    try:
        metadata = _parse_yaml_block(yaml_content)
    except _YamlBlockError as e:
        errors.append(f"Block {block_num} (line {line_number}): Invalid YAML - {e}")
        return errors, warnings, None
    if not metadata:
        errors.append(
            f"Block {block_num} (line {line_number}): YAML metadata must be a mapping"
        )
        return errors, warnings, None

    # Validate required fields
    field_errors = _validate_fields(block_num, line_number, metadata)
    if field_errors:
        errors.extend(field_errors)
        return errors, warnings, None

    # Extract description (content after YAML block)
    yaml_end = yaml_match.end()
    description_content = content[yaml_end:].strip()

    # Also include any content before the YAML block but after H2
    h2_end = h2_match.end()
    yaml_start = yaml_match.start()
    pre_yaml_content = content[h2_end:yaml_start].strip()

    # Combine pre-YAML and post-YAML content
    if pre_yaml_content and description_content:
        description = f"{pre_yaml_content}\n\n{description_content}"
    elif pre_yaml_content:
        description = pre_yaml_content
    else:
        description = description_content

    if not description:
        warnings.append(
            f"Block {block_num} (line {line_number}): Empty description for '{summary}'"
        )
        description = ""

    # Extract known fields (all validated above, so scalars are well-formed)
    issue_type_str = metadata["issue_type"].strip().lower()
    story_points_raw = metadata.get("story_points")
    link_type_str = metadata.get("link_type")
    link_type_raw = link_type_str.strip().lower() if link_type_str else None

    # Extract optional fields with safe handling
    epic_key_raw = metadata.get("epic_key")
    epic_key = epic_key_raw.strip() or None if epic_key_raw else None
    link_to_raw = metadata.get("link_to")
    link_to = link_to_raw.strip() or None if link_to_raw else None

    # Build extra_fields from unknown keys
    known_fields = REQUIRED_FIELDS | OPTIONAL_FIELDS
    extra_fields: dict[str, Any] = {}
    for key, value in metadata.items():
        if key not in known_fields:
            extra_fields[key] = value

    ticket = MarkdownTicket(
        project_id=metadata["project_id"].strip(),
        issue_type=IssueType(issue_type_str),
        summary=summary,
        component=metadata["component"].strip(),
        description=description,
        epic_key=epic_key,
        story_points=int(story_points_raw) if story_points_raw is not None else None,
        link_to=link_to,
        link_type=LinkType(link_type_raw) if link_type_raw else None,
        extra_fields=extra_fields,
        line_number=line_number,
    )
    return errors, warnings, ticket


def _validate_fields(
    block_num: int, line_number: int, metadata: dict[str, Any]
) -> list[str]:
    """Validate ticket metadata fields.

    Args:
        block_num: Block number for error messages.
        line_number: Line number for error messages.
        metadata: Parsed YAML metadata.

    Returns:
        List of error messages.
    """
    errors: list[str] = []

    # Check required fields
    for field_name in REQUIRED_FIELDS:
        value = metadata.get(field_name)
        if not value or (isinstance(value, str) and not value.strip()):
            errors.append(
                f"Block {block_num} (line {line_number}): '{field_name}' is required but missing"
            )

    # Early return if required fields missing
    if errors:
        return errors

    # Validate issue_type
    issue_type_str = metadata.get("issue_type", "").strip().lower()
    valid_types = {t.value for t in IssueType}
    if issue_type_str not in valid_types:
        errors.append(
            f"Block {block_num} (line {line_number}): Invalid issue_type '{issue_type_str}'. "
            f"Must be one of: {', '.join(sorted(valid_types))}"
        )
        return errors

    # Validate epic-excluded fields
    if issue_type_str == IssueType.EPIC.value:
        for field_name in EPIC_EXCLUDED_FIELDS:
            value = metadata.get(field_name)
            if value and (not isinstance(value, str) or value.strip()):
                errors.append(
                    f"Block {block_num} (line {line_number}): "
                    f"'{field_name}' is not allowed for epic issue type"
                )

    # Validate story_points is numeric if provided
    story_points = metadata.get("story_points")
    if story_points is not None and not isinstance(story_points, int | float):
        try:
            int(story_points)
        except (ValueError, TypeError):
            errors.append(
                f"Block {block_num} (line {line_number}): "
                f"'story_points' must be a number, got '{story_points}'"
            )

    # Validate link_type if provided
    link_type_str = metadata.get("link_type")
    link_to = metadata.get("link_to")
    if link_type_str or link_to:
        errors.append(
            f"Block {block_num} (line {line_number}): issue links are not supported "
            "by the creator"
        )
    if link_type_str:
        link_type_str = str(link_type_str).strip().lower()
        valid_link_types = {t.value for t in LinkType}
        if link_type_str not in valid_link_types:
            errors.append(
                f"Block {block_num} (line {line_number}): Invalid link_type '{link_type_str}'. "
                f"Must be one of: {', '.join(sorted(valid_link_types))}"
            )

    # Validate link_to format if provided
    if link_to:
        link_to = str(link_to).strip()
        if not _is_valid_ticket_key(link_to):
            errors.append(
                f"Block {block_num} (line {line_number}): Invalid link_to '{link_to}'. "
                "Expected format: PROJECT-123"
            )

    # Validate epic_key format if provided
    epic_key = metadata.get("epic_key")
    if epic_key:
        epic_key = str(epic_key).strip()
        if epic_key.upper() == "NEW":
            errors.append(
                f"Block {block_num} (line {line_number}): epic_key 'NEW' is not "
                "supported by the creator"
            )
        elif not _is_valid_ticket_key(epic_key):
            errors.append(
                f"Block {block_num} (line {line_number}): Invalid epic_key '{epic_key}'. "
                "Expected format: PROJECT-123"
            )

    return errors


def _is_valid_ticket_key(key: str) -> bool:
    """Check if a string looks like a valid Jira ticket key."""
    return TICKET_KEY_PATTERN.fullmatch(key) is not None
