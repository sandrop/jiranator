"""Subprocess-boundary smoke test for the enricher push path.

Per docs/patterns/subprocess-boundary-smoke.md: a fresh subprocess imports
``enhance`` / ``enhance_rest`` and runs the real fetch -> enrich -> update seam
over an injected fake transport, then this test reads the ADF body that
subprocess actually PUT. No network, no credentials, no in-process call: both
the write side effect AND the fail-loud degradation guard are asserted across
the process boundary.
"""

import json
import subprocess
import sys
from pathlib import Path

LIB = Path(__file__).resolve().parent.parent / "lib"

_DRIVER = """
import json
import sys
sys.path.insert(0, {lib!r})
import enhance
import enhance_rest

templates = {templates!r}
out = {out!r}

class FakeHttp:
    def __init__(self, issue):
        self._issue = issue
        self.put_body = None
    def get_json(self, path, params=None):
        return self._issue
    def post_json(self, path, body):
        raise AssertionError("unused")
    def put_json(self, path, body):
        self.put_body = body

issue = {{"key": "SMK-1", "fields": {{"issuetype": {{"name": "Story"}}}}}}
http = FakeHttp(issue)

fetched = enhance_rest.fetch_issue(http, "SMK-1")
skeleton = enhance.enrich_description(fetched, templates)

# The fail-loud guard must refuse an unfilled skeleton (leftover TODO markers).
try:
    enhance_rest.update_issue_description(http, "SMK-1", skeleton)
    raise SystemExit("guard did not fire on unfilled skeleton")
except ValueError:
    print("GUARD_OK")

# Fill the TODO markers, then the push succeeds and records the ADF body.
filled = "\\n".join(
    "filled." if enhance.TODO_MARKER in line else line
    for line in skeleton.splitlines()
) + "\\n"
enhance_rest.update_issue_description(http, "SMK-1", filled)
with open(out, "w", encoding="utf-8") as fh:
    json.dump(http.put_body, fh)
"""


def _seed_story(tmp_path):
    tdir = tmp_path / "templates"
    tdir.mkdir()
    (tdir / "story.md").write_text(
        "### Description\n<!-- TODO: Add description -->\n\n"
        "### Acceptance Criteria\n<!-- TODO: Define acceptance criteria -->\n",
        encoding="utf-8",
    )
    return tdir


def test_enhance_subprocess_pushes_adf_and_enforces_guard(tmp_path):
    tdir = _seed_story(tmp_path)
    out = tmp_path / "put_body.json"
    driver = tmp_path / "driver.py"
    driver.write_text(
        _DRIVER.format(lib=str(LIB), templates=str(tdir), out=str(out)),
        encoding="utf-8",
    )

    r = subprocess.run([sys.executable, str(driver)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "Traceback" not in r.stderr
    assert "GUARD_OK" in r.stdout

    body = json.loads(out.read_text(encoding="utf-8"))
    doc = body["fields"]["description"]
    assert doc["type"] == "doc" and doc["version"] == 1
    headings = [
        node["content"][0]["text"]
        for node in doc["content"]
        if node["type"] == "heading"
    ]
    assert headings == ["Description", "Acceptance Criteria"]
