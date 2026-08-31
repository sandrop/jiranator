"""Fresh-subprocess smoke for the installed command component names."""

import shutil
import subprocess
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
CLI = PLUGIN / "cli" / "jiranator.py"


def test_claude_loader_registers_bare_command_components():
    claude = shutil.which("claude")
    assert claude is not None, "claude CLI is required for the install-boundary smoke"

    result = subprocess.run(
        [claude, "--plugin-dir", str(PLUGIN), "plugin", "details", "jiranator"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    inventory = next(
        line
        for line in result.stdout.splitlines()
        if line.strip().startswith("Skills (6)")
    )
    components = {name.strip() for name in inventory.split(")", 1)[1].split(",")}
    assert components == {"menu", "download", "enrich", "update", "create", "convert"}


def test_menu_selection_dispatches_target_in_fresh_subprocess():
    result = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "menu",
            "1",
            "--arguments",
            "project = SMOKE",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "# Download Jira Issues" in result.stdout
    assert "Arguments: project = SMOKE" in result.stdout
    assert "$ARGUMENTS" not in result.stdout
