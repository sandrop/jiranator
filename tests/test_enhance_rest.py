"""Tests for the REST enricher over the injected transport seam.

``enhance_rest`` is rewritten off legacy ``requests`` onto the plugin's
``HttpTransport`` (``get_json`` / ``put_json``); a ``FakeHttp`` records calls so
the suite never touches the network. The verbatim degradation guard
(markdown -> ADF warnings -> ``refusing to push``) is pinned here: it is the
deterministic backstop before any PUT.
"""

import pytest

import enhance_rest


class FakeHttp:
    def __init__(self, get_result=None):
        self.get_result = get_result or {}
        self.puts = []
        self.gets = []

    def get_json(self, path, params=None):
        self.gets.append((path, params))
        return self.get_result

    def post_json(self, path, body):
        raise AssertionError("post_json is unused on the enrich path")

    def put_json(self, path, body):
        self.puts.append((path, body))


def test_fetch_issue_hits_rest_v3_and_returns_body():
    http = FakeHttp({"key": "PROJ-1", "fields": {}})
    body = enhance_rest.fetch_issue(http, "PROJ-1")
    assert body["key"] == "PROJ-1"
    path, params = http.gets[0]
    assert path == "/rest/api/3/issue/PROJ-1"
    assert "description" in params["fields"]
    assert "customfield_10004" not in params["fields"]


def test_fetch_issue_rejects_bad_key():
    with pytest.raises(ValueError):
        enhance_rest.fetch_issue(FakeHttp(), "bad key")


def test_update_puts_adf_payload():
    http = FakeHttp()
    enhance_rest.update_issue_description(http, "PROJ-1", "### Description\n\nHello\n")
    path, body = http.puts[0]
    assert path == "/rest/api/3/issue/PROJ-1"
    assert body["fields"]["description"]["type"] == "doc"


def test_update_refuses_on_adf_degradation():
    http = FakeHttp()
    with pytest.raises(ValueError, match="refusing to push"):
        enhance_rest.update_issue_description(http, "PROJ-1", "# H1 heading\n")
    assert http.puts == []


def test_update_rejects_bad_key():
    with pytest.raises(ValueError):
        enhance_rest.update_issue_description(FakeHttp(), "bad key", "### x\n")


def test_update_rejects_blank_description():
    with pytest.raises(ValueError):
        enhance_rest.update_issue_description(FakeHttp(), "PROJ-1", "   \n")
