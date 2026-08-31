"""Behavioral tests for the production ``JiraHttp`` client.

Exercises the real client through its injectable opener seam: request method,
URL, Basic-auth header, JSON body, query encoding, redirect refusal, and the
HTTP / URL / non-JSON error mapping to ``JiraHttpError``. Also pins the
https-only construction guard. No network.
"""

import base64
import io
import urllib.error

import jira_http
import pytest


class _Cfg:
    def __init__(self, instance_url):
        self.instance_url = instance_url


class _Creds:
    # Not an email literal on purpose: the publish leak-check forbids any
    # email-shaped string in a shipped plugin. Only the base64(email:token)
    # header value matters here, so an opaque identity keeps the gate green.
    email = "jira-user"
    api_token = "s3cr3t"


class _Resp:
    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    """Stands in for the urllib opener: records the request, returns a body or
    raises a preset exception."""

    def __init__(self, body: bytes = b"{}", exc: Exception | None = None):
        self.body = body
        self.exc = exc
        self.last_req = None
        self.last_timeout = None

    def open(self, req, timeout=None):
        self.last_req = req
        self.last_timeout = timeout
        if self.exc is not None:
            raise self.exc
        return _Resp(self.body)


def _client(opener, instance_url="https://ex.atlassian.net"):
    return jira_http.JiraHttp(_Cfg(instance_url), _Creds(), opener=opener)


def _expected_auth():
    raw = f"{_Creds.email}:{_Creds.api_token}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def test_post_json_builds_authenticated_post():
    op = FakeOpener(body=b'{"issues": []}')
    out = _client(op).post_json("/rest/api/3/search/jql", {"jql": "project = X"})

    assert out == {"issues": []}
    req = op.last_req
    assert req.full_url == "https://ex.atlassian.net/rest/api/3/search/jql"
    assert req.get_method() == "POST"
    assert req.data == b'{"jql": "project = X"}'
    assert req.get_header("Authorization") == _expected_auth()
    assert req.get_header("Content-type") == "application/json"


def test_get_json_encodes_query_params():
    op = FakeOpener(body=b'{"values": []}')
    out = _client(op).get_json(
        "/rest/api/3/issue/GDP-1/changelog", {"startAt": 0, "maxResults": 100}
    )

    assert out == {"values": []}
    req = op.last_req
    assert req.get_method() == "GET"
    assert req.full_url == (
        "https://ex.atlassian.net/rest/api/3/issue/GDP-1/changelog"
        "?startAt=0&maxResults=100"
    )
    assert req.get_header("Authorization") == _expected_auth()


def test_redirect_is_refused():
    handler = jira_http._NoRedirect()
    assert (
        handler.redirect_request(None, None, 302, "Found", {}, "https://evil.example")
        is None
    )


def test_http_error_maps_to_jira_http_error():
    err = urllib.error.HTTPError(
        url="https://ex.atlassian.net/x",
        code=401,
        msg="Unauthorized",
        hdrs=None,
        fp=io.BytesIO(b"denied"),
    )
    with pytest.raises(jira_http.JiraHttpError) as excinfo:
        _client(FakeOpener(exc=err)).post_json("/x", {})
    assert "401" in str(excinfo.value)


def test_url_error_maps_to_jira_http_error():
    with pytest.raises(jira_http.JiraHttpError):
        _client(FakeOpener(exc=urllib.error.URLError("connection refused"))).get_json(
            "/x"
        )


def test_non_json_body_maps_to_jira_http_error():
    with pytest.raises(jira_http.JiraHttpError):
        _client(FakeOpener(body=b"<html>not json</html>")).post_json("/x", {})


def test_put_json_accepts_204_no_content():
    # Jira REST v3 answers a description PUT with 204 No Content + empty body;
    # put_json must return None (not attempt json.loads on "") and build an
    # authenticated PUT with the ADF payload.
    op = FakeOpener(body=b"")
    out = _client(op).put_json(
        "/rest/api/3/issue/PROJ-1", {"fields": {"description": {"type": "doc"}}}
    )

    assert out is None
    req = op.last_req
    assert req.get_method() == "PUT"
    assert req.full_url == "https://ex.atlassian.net/rest/api/3/issue/PROJ-1"
    assert req.data == b'{"fields": {"description": {"type": "doc"}}}'
    assert req.get_header("Authorization") == _expected_auth()


def test_put_json_maps_http_error():
    err = urllib.error.HTTPError(
        url="https://ex.atlassian.net/x",
        code=403,
        msg="Forbidden",
        hdrs=None,
        fp=io.BytesIO(b"denied"),
    )
    with pytest.raises(jira_http.JiraHttpError) as excinfo:
        _client(FakeOpener(exc=err)).put_json("/x", {})
    assert "403" in str(excinfo.value)


def test_http_instance_url_is_rejected():
    with pytest.raises(jira_http.JiraHttpError):
        _client(FakeOpener(), instance_url="http://ex.atlassian.net")


def test_scheme_relative_instance_url_is_rejected():
    with pytest.raises(jira_http.JiraHttpError):
        _client(FakeOpener(), instance_url="ex.atlassian.net")
