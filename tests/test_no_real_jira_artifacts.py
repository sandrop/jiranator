import re
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
# Synthetic placeholder hosts used across the suite. None is a real tenant:
# `your-org`/`ex` are example/config placeholders; `real` is the enhance tests'
# stand-in for "a non-placeholder user config" (i.e. not the seeded example).
ALLOWED_HOSTS = {"your-org.atlassian.net", "ex.atlassian.net", "real.atlassian.net"}
HOST_RE = re.compile(r"https?://([a-z0-9.-]+\.atlassian\.net)")


def _files():
    for p in sorted(PLUGIN.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts:
            yield p


def test_no_non_placeholder_jira_hosts():
    hits = []
    for f in _files():
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for host in HOST_RE.findall(line):
                if host not in ALLOWED_HOSTS:
                    hits.append(f"{f.relative_to(PLUGIN)}:{i}: {host}")
    assert not hits, "non-placeholder Jira hosts in shipped code:\n" + "\n".join(hits)
