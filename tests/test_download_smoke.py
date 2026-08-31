"""Subprocess-boundary smoke test for the unified downloader.

Per docs/patterns/subprocess-boundary-smoke.md: a fresh subprocess
imports ``downloader`` and runs a real ``download`` over an injected fake
transport, then this test reads the files that subprocess actually wrote. No
network, no credentials, no in-process call: the persistence side effect is
asserted across the process boundary.
"""

import json
import subprocess
import sys
from pathlib import Path

LIB = Path(__file__).resolve().parent.parent / "lib"

_DRIVER = """
import sys
sys.path.insert(0, {lib!r})
import downloader

class FakeHttp:
    def __init__(self, pages):
        self.pages = list(pages)
    def post_json(self, path, body):
        return self.pages.pop(0)
    def get_json(self, path, params=None):
        return {{"values": []}}

issue = {{
    "id": "9", "key": "SMK-1", "self": "https://x/rest/api/3/issue/9",
    "fields": {{"summary": "smoke", "issuetype": {{"name": "Story"}}}},
    "changelog": {{"total": 1, "histories": [{{
        "author": {{"displayName": "Bot", "accountId": "557:z"}},
        "created": "2026-08-24T10:00:00.000+0200",
        "items": [{{"field": "status", "fromString": "To Do", "toString": "Done"}}],
    }}]}},
}}
page = {{"issues": [issue], "isLast": True, "nextPageToken": None}}
downloader.download(FakeHttp([page]), "project = SMOKE", out_dir={out!r})
"""


def test_download_subprocess_writes_snapshot(tmp_path):
    out_dir = tmp_path / "snap"
    driver = tmp_path / "driver.py"
    driver.write_text(_DRIVER.format(lib=str(LIB), out=str(out_dir)), encoding="utf-8")

    r = subprocess.run(
        [sys.executable, str(driver)],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    assert "Traceback" not in r.stderr

    lines = (out_dir / "issues.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["key"] == "SMK-1"
    assert record["status_transitions"][0]["to_status"] == "Done"

    meta = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["jql"] == "project = SMOKE"
    assert meta["schema_version"] == "1.0"

    assert (out_dir / "download.complete").exists()
