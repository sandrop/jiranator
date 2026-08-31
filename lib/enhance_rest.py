"""REST enricher: fetch an issue and update its description via the transport seam.

Ported from legacy ``jirainator.enhance_rest`` but rewritten off ``requests``
onto the plugin's injected :class:`~jira_http.HttpTransport` (``get_json`` /
``put_json``): production wires a stdlib ``JiraHttp``, tests inject a fake and
never hit the network. The legacy ``requests``-based transport, ``JiraConfig``
auth wiring, ``_scrub_auth_tokens``, and ``_raise_for_status`` taxonomy are
dropped; the non-2xx / non-JSON error taxonomy now lives in ``jira_http`` and
surfaces as ``JiraHttpError``.

The degradation guard is preserved verbatim: markdown is converted to ADF via
``adf.markdown_to_adf_with_warnings`` and the PUT is refused on ANY warning
(unclosed delimiters, unsupported blocks, dropped HTML comments). This is the
deterministic fail-loud backstop per CLAUDE.md; a confirm-push gate lives
upstream in the CLI.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import adf
from enhance import KEY_RE

if TYPE_CHECKING:
    # Annotation-only; the runtime dependency is the duck-typed transport surface.
    from jira_http import HttpTransport

_FETCH_FIELDS: tuple[str, ...] = (
    "summary",
    "description",
    "issuetype",
    "status",
    "components",
    "comment",
)
# Both endpoints converge on REST v3: fetch_issue reads the ADF description,
# update_issue_description PUTs an ADF body. Sending markdown to v3 returns 400.
_REST_VERSION = "3"


def _issue_path(key: str) -> str:
    return f"/rest/api/{_REST_VERSION}/issue/{key}"


def fetch_issue(http: HttpTransport, key: str) -> dict[str, Any]:
    """GET ``/rest/api/3/issue/{key}`` for the enrich field set. Raises
    ``ValueError`` on a malformed key; transport errors surface as
    ``JiraHttpError`` from the injected client."""
    if not KEY_RE.match(key):
        raise ValueError(f"invalid issue key: {key}")
    return http.get_json(_issue_path(key), {"fields": ",".join(_FETCH_FIELDS)})


def update_issue_description(
    http: HttpTransport, key: str, description_markdown: str
) -> None:
    """PUT a new description onto a Jira issue via REST v3 with an ADF body.

    The markdown is converted to ADF via ``adf.markdown_to_adf_with_warnings`` and
    PUT against ``/rest/api/3/issue/{key}``. Jira REST v3 requires ADF; sending a
    markdown string returns HTTP 400. Refuses the push (``ValueError``) if the
    converter surfaced ANY degradation warning -- the fail-loud backstop.
    """
    if not KEY_RE.match(key):
        raise ValueError(f"invalid issue key: {key}")
    if not description_markdown.strip():
        raise ValueError("description required")
    adf_doc, warnings = adf.markdown_to_adf_with_warnings(description_markdown)
    if warnings:
        raise ValueError(
            f"refusing to push: {len(warnings)} markdown-to-ADF degradations: {warnings}"
        )
    http.put_json(_issue_path(key), {"fields": {"description": adf_doc}})
