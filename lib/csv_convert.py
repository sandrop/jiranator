"""CSV -> markdown-with-YAML converter for the jiranator creator path.

Reads a CSV of ticket rows and renders the markdown-with-YAML intermediate that
``markdown_parser.parse_markdown`` consumes. Each row becomes one block: an H2
summary, a fenced ``yaml`` metadata frontmatter carrying every column except
``summary`` (the H2) and ``description`` (folded into the body), then the
issue-type body read from the shared enricher templates (AC #4) with the row
description substituted into its leading section. Blocks are joined with
``\\n\\n---\\n\\n`` and the document has no leading delimiter.

Fail loud: missing required columns or empty required values raise
``CsvConvertError`` carrying a ``list[str]`` of ``Row N``-scoped messages; an
unknown issue type or a missing template file surfaces the same way.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from enhance import select_template
from markdown_parser import EPIC_EXCLUDED_FIELDS

# Columns every row must carry with a non-empty value.
REQUIRED_COLUMNS = ("project_id", "issue_type", "component", "summary")

# Columns consumed outside the YAML block: the H2 header and the body.
_NON_YAML_COLUMNS = frozenset({"summary", "description"})


class CsvConvertError(Exception):
    """Error during CSV conversion, carrying per-row messages."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__(f"CSV conversion failed with {len(errors)} error(s)")


def convert_csv(csv_path: Path, templates_dir: Path) -> str:
    """Convert a CSV file to the markdown-with-YAML creator intermediate.

    Args:
        csv_path: Path to the source CSV (a header row plus one row per ticket).
        templates_dir: Directory of issue-type template bodies (shared with the
            enricher), resolved by the caller via ``config.templates_dir``.

    Returns:
        The full markdown document: one block per row, ``---``-delimited, with
        no leading delimiter.

    Raises:
        CsvConvertError: On unreadable input, missing required columns, empty
            required values, or an unknown issue type / missing template.
    """
    try:
        text = Path(csv_path).read_text(encoding="utf-8-sig")
    except UnicodeError as e:
        raise CsvConvertError([f"CSV at {csv_path} is not valid UTF-8 ({e})."]) from e
    except OSError as e:
        raise CsvConvertError([f"Could not read CSV at {csv_path} ({e})."]) from e

    reader = csv.DictReader(text.splitlines(keepends=True))
    fieldnames = reader.fieldnames or []
    missing_columns = [c for c in REQUIRED_COLUMNS if c not in fieldnames]
    if missing_columns:
        raise CsvConvertError(
            [f"CSV missing required column(s): {', '.join(missing_columns)}"]
        )

    errors: list[str] = []
    blocks: list[str] = []
    for row_num, row in enumerate(reader, start=1):
        if None in row:
            errors.append(f"Row {row_num}: row has more values than columns")
            continue
        row_errors = [
            f"Row {row_num}: '{col}' is required but empty"
            for col in REQUIRED_COLUMNS
            if not (row.get(col) or "").strip()
        ]
        if any(char in (row.get("summary") or "") for char in "\r\n"):
            row_errors.append(f"Row {row_num}: summary must be one line")
        if row_errors:
            errors.extend(row_errors)
            continue
        try:
            blocks.append(_render_block(row, templates_dir))
        except ValueError as e:
            errors.append(f"Row {row_num}: {e}")

    if errors:
        raise CsvConvertError(errors)

    return "\n\n---\n\n".join(blocks)


def _render_block(row: dict[str, str], templates_dir: Path) -> str:
    """Render one CSV row as a markdown ticket block.

    Raises:
        ValueError: When the issue type is unknown or its template is missing
            (propagated from ``select_template``).
    """
    summary = row["summary"].strip()
    issue_type = row["issue_type"].strip().lower()
    excluded = EPIC_EXCLUDED_FIELDS if issue_type == "epic" else frozenset()

    yaml_lines = []
    for col, raw in row.items():
        if col is None or col in _NON_YAML_COLUMNS or col in excluded:
            continue
        value = (raw or "").strip()
        # Empty values render as a bare ``field:`` (parsed back as absent).
        encoded = json.dumps(value, ensure_ascii=False) if value else ""
        yaml_lines.append(f"{col}: {encoded}".rstrip())

    body = _inject_description(
        select_template(issue_type, templates_dir),
        (row.get("description") or "").strip(),
    )

    parts = [f"## {summary}", "", "```yaml", *yaml_lines, "```", "", body.rstrip(), ""]
    return "\n".join(parts)


def _inject_description(body: str, description: str) -> str:
    """Substitute ``description`` for the first ``<!-- TODO`` placeholder.

    The leading section of every issue-type template is the description block; a
    non-empty row description replaces its TODO placeholder line. An empty
    description leaves the template skeleton untouched.
    """
    if not description:
        return body
    lines = body.splitlines()
    first_heading = next(
        (index for index, line in enumerate(lines) if line.startswith("### ")), None
    )
    if first_heading is None:
        raise ValueError("custom template leading section has no TODO placeholder")
    next_heading = next(
        (
            index
            for index, line in enumerate(lines[first_heading + 1 :], first_heading + 1)
            if line.startswith("### ")
        ),
        len(lines),
    )
    for i in range(first_heading + 1, next_heading):
        line = lines[i]
        if "<!-- TODO" in line:
            lines[i] = description
            return "\n".join(lines)
    raise ValueError("custom template leading section has no TODO placeholder")
