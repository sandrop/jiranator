import re
from pathlib import Path

COMMANDS = Path(__file__).resolve().parent.parent / "commands"
PHASE1 = (
    "download",
    "enrich",
    "update",
    "create",
)


def _frontmatter(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path.name}: missing opening frontmatter fence"
    end = text.index("\n---", 4)
    return text[4:end]


def test_phase1_command_files_present():
    missing = [n for n in PHASE1 if not (COMMANDS / f"{n}.md").is_file()]
    assert not missing, f"missing Phase 1 command files: {missing}"


def test_menu_command_present():
    assert (COMMANDS / "menu.md").is_file(), "menu command menu.md missing"


def test_command_files_have_description_frontmatter():
    for n in PHASE1 + ("menu",):
        fm = _frontmatter(COMMANDS / f"{n}.md")
        assert "description:" in fm, f"{n}.md: frontmatter has no description:"


def test_menu_lists_exactly_the_four_phase1_commands():
    body = (COMMANDS / "menu.md").read_text(encoding="utf-8")
    for cmd in PHASE1:
        command = f"/jiranator:{cmd}"
        assert command in body, f"menu does not dispatch to {command}"
    assert "/jiranator:convert" not in body, "convert must not be a menu entry"


# Each command file must invoke its mapped CLI subcommand. The invocation is
# written with the shipped convention -- a shell-quoted plugin root, e.g.
# `"${CLAUDE_PLUGIN_ROOT}/cli/jiranator.py" download` -- so match the subcommand
# token after `jiranator.py` tolerant of the closing quote.
CLI_SUBCOMMAND = {
    "download": "download",
    "enrich": "enhance",
    "update": "enhance",
}


def test_commands_invoke_mapped_cli_subcommand():
    for name, subcommand in CLI_SUBCOMMAND.items():
        body = (COMMANDS / f"{name}.md").read_text(encoding="utf-8")
        pattern = re.compile(rf'jiranator\.py"?\s+{subcommand}\b')
        assert pattern.search(
            body
        ), f"{name}.md does not invoke `jiranator.py {subcommand}`"
    update = (COMMANDS / "update.md").read_text(encoding="utf-8")
    assert "--push" in update, "update command must pass --push (write-back)"


def test_download_command_does_not_advertise_unforwarded_flags():
    body = (COMMANDS / "download.md").read_text(encoding="utf-8")
    assert "--label" not in body
    assert "--out" not in body


def test_enrich_command_describes_phase1_skeleton_contract():
    body = (COMMANDS / "enrich.md").read_text(encoding="utf-8").lower()
    assert "template skeleton" in body
    assert "does not preserve" in body


def test_update_command_requires_reviewed_description_file():
    body = (COMMANDS / "update.md").read_text(encoding="utf-8").lower()
    assert "reviewed markdown is required" in body
    assert "without it" not in body


def test_rest_commands_separate_profile_config_from_credentials():
    for name in ("download", "enrich", "update"):
        body = (COMMANDS / f"{name}.md").read_text(encoding="utf-8")
        assert "jiranator.yaml" in body
        assert "JIRA_EMAIL" in body
        assert "JIRA_API_TOKEN" in body
