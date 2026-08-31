"""Subprocess-boundary smoke for the creator CLI.

Per docs/patterns/subprocess-boundary-smoke.md: run the real jiranator CLI in a
fresh subprocess for both legs of the creator pipeline -- convert a 3-row CSV to
markdown, then build the createJiraIssue plan from that markdown -- and assert
the process boundary end to end (import wiring, argparse, module resolution, and
first-run template seeding). No MCP, no network, no credentials.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

CLI = Path(__file__).resolve().parent.parent / "cli" / "jiranator.py"


def test_convert_then_create_over_cli_subprocess(tmp_path):
    env = {**os.environ, "CLAUDE_CONFIG_DIR": str(tmp_path)}
    env.pop("JIRA_EMAIL", None)
    env.pop("JIRA_API_TOKEN", None)

    csv_path = tmp_path / "tickets.csv"
    csv_path.write_text(
        "project_id,issue_type,component,summary,epic_key,story_points,description\n"
        "PROJ,story,Frontend,Login Form,PROJ-100,5,Log in with email\n"
        "PROJ,task,Backend,Auth Middleware,PROJ-100,3,Configure JWT\n"
        "PROJ,epic,Platform,Platform Epic,,,Platform overview\n",
        encoding="utf-8",
    )
    md_path = tmp_path / "tickets.md"

    convert = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "convert",
            "--csv",
            str(csv_path),
            "--out",
            str(md_path),
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    assert convert.returncode == 0, convert.stderr
    assert "Traceback" not in convert.stderr
    assert md_path.exists()
    config_dir = tmp_path / ".sct" / "jiranator" / "config"
    (config_dir / "jiranator.yaml").write_text(
        'field_ids:\n  story_points: "customfield_10016"\n'
        "story_points_field_confirmed: true\n",
        encoding="utf-8",
    )

    create = subprocess.run(
        [sys.executable, str(CLI), "create", "--file", str(md_path)],
        capture_output=True,
        text=True,
        env=env,
    )
    assert create.returncode == 0, create.stderr
    assert "Traceback" not in create.stderr

    plan = json.loads(create.stdout)
    assert len(plan) == 3
    first = plan[0]
    assert first["projectKey"] == "PROJ"
    assert first["issueTypeName"] == "Story"
    assert first["additional_fields"]["components"] == [{"name": "Frontend"}]
    assert first["parent"] == "PROJ-100"
    assert "parent" not in first["additional_fields"]
    assert first["additional_fields"]["customfield_10016"] == 5

    epic = plan[2]
    assert epic["issueTypeName"] == "Epic"
    assert "parent" not in epic
    assert "customfield_10016" not in epic["additional_fields"]
