"""Injectable stdlib HTTP seam for the jiranator REST client.

Transport is stdlib-only: ``urllib.request`` with HTTP Basic auth, matching the
``ccu`` plugin's ``usage_source.py`` (no plugin imports ``requests``; keeps
jiranator zero-install). The concrete ``JiraHttp`` is constructed from a
``JiraConfig.instance_url`` plus ``JiraCredentials`` (email + API token); the
downloader depends only on the ``post_json`` / ``get_json`` surface, so tests
inject a fake and never touch the network.

Basic-auth contract: every request carries
``Authorization: Basic base64(email:api_token)``. Redirects are refused so the
credential header is never re-sent to a redirect target (a TLS-intercepting
proxy could 3xx the request and capture the token); the Jira REST endpoints
under an instance host should never redirect.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Mapping, Optional, Protocol, runtime_checkable

_TIMEOUT_S = 60


@runtime_checkable
class HttpTransport(Protocol):
    """The narrow surface the downloader depends on; ``JiraHttp`` and the test
    fakes both satisfy it."""

    def post_json(self, path: str, body: Mapping[str, Any]) -> dict: ...

    def get_json(
        self, path: str, params: Optional[Mapping[str, Any]] = None
    ) -> dict: ...

    def put_json(self, path: str, body: Mapping[str, Any]) -> None: ...


class JiraHttpError(RuntimeError):
    """Raised when a Jira REST call returns a non-2xx status or a non-JSON body."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects so the Basic-auth header is never re-sent elsewhere."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # do not follow; the 3xx falls through as an error


def _build_no_redirect_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(_NoRedirect)


class JiraHttp:
    """Concrete ``urllib``-backed Jira REST client with HTTP Basic auth."""

    def __init__(self, config, credentials, *, timeout: int = _TIMEOUT_S, opener=None):
        # Require an absolute https URL before any authenticated request is
        # built: an http:// instance_url would send the Basic-auth token in
        # clear text, and refusing redirects does not protect the first hop.
        parsed = urllib.parse.urlparse(config.instance_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise JiraHttpError(
                "instance_url must be an absolute https URL, got "
                f"{config.instance_url!r}"
            )
        self._base_url = config.instance_url.rstrip("/")
        raw = f"{credentials.email}:{credentials.api_token}".encode("utf-8")
        self._auth = "Basic " + base64.b64encode(raw).decode("ascii")
        self._timeout = timeout
        self._opener = opener or _build_no_redirect_opener()

    def _headers(self) -> dict:
        return {
            "Authorization": self._auth,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _open(self, req: urllib.request.Request, *, allow_empty: bool = False) -> dict:
        try:
            with self._opener.open(req, timeout=self._timeout) as resp:
                body = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:  # non-2xx
            detail = (exc.read().decode("utf-8", "replace") or "")[:500]
            raise JiraHttpError(
                f"Jira API error {exc.code} for {req.full_url}: {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise JiraHttpError(
                f"Jira request to {req.full_url} failed: {exc.reason}"
            ) from exc
        # A write that answers 204 No Content has an empty body; json.loads("")
        # would raise. allow_empty callers (put_json) tolerate it and return {}.
        if allow_empty and not body.strip():
            return {}
        try:
            return json.loads(body)
        except ValueError as exc:
            raise JiraHttpError(
                f"Jira returned non-JSON from {req.full_url}: {body[:300]}"
            ) from exc

    def post_json(self, path: str, body: Mapping[str, Any]) -> dict:
        url = f"{self._base_url}{path}"
        data = json.dumps(dict(body)).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, headers=self._headers(), method="POST"
        )
        return self._open(req)

    def get_json(self, path: str, params: Optional[Mapping[str, Any]] = None) -> dict:
        url = f"{self._base_url}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(dict(params))}"
        req = urllib.request.Request(url, headers=self._headers(), method="GET")
        return self._open(req)

    def put_json(self, path: str, body: Mapping[str, Any]) -> None:
        url = f"{self._base_url}{path}"
        data = json.dumps(dict(body)).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, headers=self._headers(), method="PUT"
        )
        # Jira returns 204 No Content on a successful description update; tolerate
        # the empty body. A non-2xx status still raises JiraHttpError via _open.
        self._open(req, allow_empty=True)
