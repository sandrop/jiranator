"""Markdown -> ADF converter for the jiranator enhance template subset.

Ported verbatim from the legacy ``jirainator.adf`` module: it is already
stdlib-only (no ``requests``, no ``pydantic``) and carries no package-relative
imports, so it lands unchanged apart from this docstring's plugin naming.

Supported (locked): `### h3`, paragraphs, `- bullets`, `1. ordered`,
fenced code blocks (with optional language), inline ``code``, ``**bold**``,
``*italic*``, and ``[text](url)`` links. Anything else (h1/h2/h4-h6, blockquotes,
tables, raw HTML) drops to a literal paragraph and emits a warning. Unclosed
inline delimiters and skipped HTML comment lines also emit warnings.

Two-function surface:
- `markdown_to_adf(md) -> ADFDoc` -- simple back-compat wrapper.
- `markdown_to_adf_with_warnings(md) -> (ADFDoc, list[str])` -- used by the
  push path to fail loud on any downgrade before writing to Jira.
"""

from __future__ import annotations

import re
from typing import Any

_ORDERED_LIST_RE = re.compile(r"^(\d+)\.\s(.*)$")
_INLINE_CODE_SPAN_RE = re.compile(r"`[^`]*`")
_RAW_HTML_TAG_RE = re.compile(r"</?[A-Za-z][^>]*>")
_TABLE_DELIMITER_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")
# Finding 6: link scheme allowlist. Reject anything not in this set (or
# relative paths starting with `/` or `#`).
_ALLOWED_LINK_SCHEMES: frozenset[str] = frozenset({"http", "https", "mailto"})

ADFDoc = dict[str, Any]


def _without_inline_code(text: str) -> str:
    return _INLINE_CODE_SPAN_RE.sub("", text)


def _is_table_line(lines: list[str], index: int) -> bool:
    stripped = lines[index].strip()
    if _TABLE_DELIMITER_RE.match(stripped):
        return True
    return (
        "|" in stripped
        and index + 1 < len(lines)
        and bool(_TABLE_DELIMITER_RE.match(lines[index + 1].strip()))
    )


def _starts_block(lines: list[str], index: int) -> bool:
    line = lines[index]
    stripped = line.strip()
    visible = _without_inline_code(line)
    return (
        not stripped
        or line.startswith(("```", "#", "- "))
        or bool(_ORDERED_LIST_RE.match(line))
        or stripped.startswith(">")
        or _is_table_line(lines, index)
        or "<!--" in visible
        or bool(_RAW_HTML_TAG_RE.search(visible))
    )


def _text_node(text: str, marks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    node: dict[str, Any] = {"type": "text", "text": text}
    if marks:
        node["marks"] = marks
    return node


def _validate_link_scheme(href: str) -> None:
    """Finding 6: raise on unsupported schemes. Allows http/https/mailto and
    relative paths starting with `/` or `#`."""
    if href.startswith(("/", "#")):
        return
    colon = href.find(":")
    if colon == -1:
        return
    if href[:colon].lower() not in _ALLOWED_LINK_SCHEMES:
        raise ValueError(f"unsupported link scheme in {href!r}")


def _find_matching_close_paren(text: str, start: int) -> int:
    """Finding 2: index of the `)` that closes a link URL, balancing nested
    parens (e.g. Wikipedia `Foo_(bar)`). Returns -1 if unbalanced."""
    depth = 1
    i = start
    n = len(text)
    while i < n:
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _parse_inline(text: str, warnings: list[str]) -> list[dict[str, Any]]:
    """Tokenize inline markdown to a list of ADF text nodes.

    Priority (highest first): code > bold > italic > link. Longest-prefix wins
    for `**` vs `*`. Unclosed delimiters fall through to literal text and emit
    a warning into `warnings`. Findings 2, 4, 5, 6 all surface here.
    """
    nodes: list[dict[str, Any]] = []
    buf: list[str] = []

    def flush() -> None:
        if buf:
            nodes.append(_text_node("".join(buf)))
            buf.clear()

    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        # Priority 1: inline code (`code`).
        if ch == "`":
            end = text.find("`", i + 1)
            if end != -1:
                flush()
                nodes.append(_text_node(text[i + 1 : end], marks=[{"type": "code"}]))
                i = end + 1
                continue
            # Finding 5: unclosed inline code.
            warnings.append("unclosed inline code delimiter; treated as literal")
        # Priority 2: bold (**text**) -- check before italic so ** wins over *.
        # CommonMark-style flank rule: opening `**` cannot be followed by
        # whitespace; closing `**` cannot be preceded by whitespace. Openers
        # that fail the flank rule fall through silently (no warning) since no
        # real bold span was ever attempted.
        if (
            ch == "*"
            and i + 1 < n
            and text[i + 1] == "*"
            and i + 2 < n
            and not text[i + 2].isspace()
        ):
            end = text.find("**", i + 2)
            while end != -1 and text[end - 1].isspace():
                end = text.find("**", end + 2)
            if end != -1 and end > i + 2:
                flush()
                nodes.append(_text_node(text[i + 2 : end], marks=[{"type": "strong"}]))
                i = end + 2
                continue
            # Finding 5: opener was valid but no close found -> unclosed bold.
            warnings.append("unclosed bold delimiter; treated as literal")
        # Priority 3: italic (*text*). Same flank rule as bold.
        # Finding 4: skip candidate `end` positions that are `**` (would be
        # the second char of a bold delimiter rather than a real italic close).
        if ch == "*" and i + 1 < n and not text[i + 1].isspace():
            end = i + 1
            italic_end = -1
            while end < n:
                end = text.find("*", end)
                if end == -1:
                    break
                # `**` is not a valid italic close.
                if end + 1 < n and text[end + 1] == "*":
                    end += 2
                    continue
                # CommonMark flank rule: closing `*` not preceded by whitespace.
                if text[end - 1].isspace():
                    end += 1
                    continue
                italic_end = end
                break
            if italic_end != -1 and italic_end > i + 1:
                flush()
                nodes.append(
                    _text_node(text[i + 1 : italic_end], marks=[{"type": "em"}])
                )
                i = italic_end + 1
                continue
            # Finding 5: opener was valid but no close found -> unclosed italic.
            warnings.append("unclosed italic delimiter; treated as literal")
        # Priority 4: link ([text](url)).
        if ch == "[":
            close_bracket = text.find("]", i + 1)
            if (
                close_bracket != -1
                and close_bracket + 1 < n
                and text[close_bracket + 1] == "("
            ):
                # Finding 2: balance-counted close paren.
                close_paren = _find_matching_close_paren(text, close_bracket + 2)
                if close_paren != -1:
                    label = text[i + 1 : close_bracket]
                    href = text[close_bracket + 2 : close_paren]
                    # Finding 6: validate scheme (raises on disallowed).
                    _validate_link_scheme(href)
                    flush()
                    nodes.append(
                        _text_node(
                            label,
                            marks=[{"type": "link", "attrs": {"href": href}}],
                        )
                    )
                    i = close_paren + 1
                    continue
                # Finding 5: unclosed link.
                warnings.append("unclosed link delimiter; treated as literal")
        buf.append(ch)
        i += 1
    flush()
    return nodes


def _list_item(text: str, warnings: list[str]) -> dict[str, Any]:
    return {
        "type": "listItem",
        "content": [{"type": "paragraph", "content": _parse_inline(text, warnings)}],
    }


def markdown_to_adf_with_warnings(md: str) -> tuple[ADFDoc, list[str]]:
    """Return `(doc, warnings)`. Empty `warnings` means fully clean. One entry
    per unclosed inline delimiter, per skipped HTML comment line, and per
    unsupported block that fell through to a literal paragraph."""
    blocks: list[dict[str, Any]] = []
    warnings: list[str] = []
    lines = md.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            language = line[3:].strip()
            code_lines: list[str] = []
            opener_index = i
            j = i + 1
            closed = False
            while j < len(lines):
                if lines[j].startswith("```"):
                    closed = True
                    break
                code_lines.append(lines[j])
                j += 1
            if not closed:
                # Finding 3: no closing fence at EOF. Treat the opener line as
                # a literal text paragraph (bypassing inline parsing so the
                # leading backticks don't reopen the code-mark scanner) and
                # continue parsing from the next line.
                warnings.append(
                    "unclosed code fence; opener treated as literal paragraph"
                )
                blocks.append(
                    {"type": "paragraph", "content": [{"type": "text", "text": line}]}
                )
                i = opener_index + 1
                continue
            block: dict[str, Any] = {
                "type": "codeBlock",
                "content": [{"type": "text", "text": "\n".join(code_lines)}],
            }
            if language:
                block["attrs"] = {"language": language}
            blocks.append(block)
            i = j + 1
            continue
        visible = _without_inline_code(line)
        comment_start = visible.find("<!--")
        if comment_start != -1:
            if "-->" not in visible[comment_start + 4 :]:
                warnings.append("dropped HTML comment block")
                i += 1
                while i < len(lines):
                    if "-->" in _without_inline_code(lines[i]):
                        i += 1
                        break
                    i += 1
                continue
            if line.lstrip().startswith("<!--") and line.rstrip().endswith("-->"):
                warnings.append(f"dropped HTML comment line: {line.strip()!r}")
                i += 1
                continue
            warnings.append(f"unsupported block (raw HTML): {line.rstrip()!r}")
        if _RAW_HTML_TAG_RE.search(visible):
            warnings.append(f"unsupported block (raw HTML): {line.rstrip()!r}")
        if line.startswith("### "):
            blocks.append(
                {
                    "type": "heading",
                    "attrs": {"level": 3},
                    "content": [{"type": "text", "text": line[4:].rstrip()}],
                }
            )
            i += 1
            continue
        # Finding 9: unsupported heading levels (h1/h2/h4-h6) drop to literal
        # paragraphs but emit a warning so the push path can reject them.
        if line.startswith("#"):
            stripped = line.lstrip("#")
            if stripped.startswith(" "):
                warnings.append(
                    f"unsupported block (non-h3 heading): {line.rstrip()!r}"
                )
                blocks.append(
                    {"type": "paragraph", "content": _parse_inline(line, warnings)}
                )
                i += 1
                continue
        if line.startswith("- "):
            items: list[dict[str, Any]] = []
            while i < len(lines) and lines[i].startswith("- "):
                items.append(_list_item(lines[i][2:], warnings))
                i += 1
            blocks.append({"type": "bulletList", "content": items})
            continue
        ordered_match = _ORDERED_LIST_RE.match(line)
        if ordered_match:
            # Finding 1: honor `attrs.order` from the first item when N != 1.
            start_num = int(ordered_match.group(1))
            ordered_items: list[dict[str, Any]] = []
            while i < len(lines):
                m = _ORDERED_LIST_RE.match(lines[i])
                if not m:
                    break
                ordered_items.append(_list_item(m.group(2), warnings))
                i += 1
            block_ol: dict[str, Any] = {
                "type": "orderedList",
                "content": ordered_items,
            }
            if start_num != 1:
                block_ol["attrs"] = {"order": start_num}
            blocks.append(block_ol)
            continue
        if not line.strip():
            i += 1
            continue
        stripped = line.strip()
        if stripped.startswith(">"):
            warnings.append(f"unsupported block (blockquote): {line.rstrip()!r}")
        elif _is_table_line(lines, i):
            warnings.append(f"unsupported block (table): {line.rstrip()!r}")
        if stripped.startswith(">") or _is_table_line(lines, i):
            blocks.append(
                {"type": "paragraph", "content": _parse_inline(line, warnings)}
            )
            i += 1
            continue

        prose = [stripped]
        i += 1
        while i < len(lines) and not _starts_block(lines, i):
            prose.append(lines[i].strip())
            i += 1
        blocks.append(
            {"type": "paragraph", "content": _parse_inline(" ".join(prose), warnings)}
        )
    if not blocks:
        blocks = [{"type": "paragraph", "content": []}]
    return {"version": 1, "type": "doc", "content": blocks}, warnings


def markdown_to_adf(md: str) -> ADFDoc:
    """Simple wrapper. Returns the ADFDoc only; warnings discarded. Empty input
    returns a doc with a single empty paragraph (Jira rejects zero-content)."""
    doc, _warnings = markdown_to_adf_with_warnings(md)
    return doc
