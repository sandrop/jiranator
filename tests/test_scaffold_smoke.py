"""Subprocess-boundary smoke test for the .sct config-dir scaffold.

A fresh subprocess with a clean ``$CLAUDE_CONFIG_DIR`` must actually create the
default config dir and seed ``jiranator.example.yaml`` on a real run. Asserting
the side effect across the process boundary (not just an in-process call)
follows the subprocess-boundary-smoke pattern: the CLI's own bootstrap and env
handling get exercised end to end.
"""

import os
import subprocess
import sys
from pathlib import Path


def test_cli_subprocess_creates_and_seeds_sct_config_dir(tmp_path):
    cli = Path(__file__).resolve().parent.parent / "cli" / "jiranator.py"
    env = {**os.environ, "CLAUDE_CONFIG_DIR": str(tmp_path)}
    env.pop("JIRA_API_TOKEN", None)
    env.pop("JIRA_EMAIL", None)
    r = subprocess.run(
        [sys.executable, str(cli), "--print-config"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert r.returncode == 0, r.stderr
    cfg_dir = tmp_path / ".sct" / "jiranator" / "config"
    assert cfg_dir.is_dir()
    assert (cfg_dir / "jiranator.example.yaml").is_file()
