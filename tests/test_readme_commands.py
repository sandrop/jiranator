from pathlib import Path

README = Path(__file__).resolve().parent.parent / "README.md"


def test_readme_documents_slash_command_surface():
    text = README.read_text(encoding="utf-8")
    for cmd in (
        "/jiranator:download",
        "/jiranator:enrich",
        "/jiranator:update",
        "/jiranator:create",
    ):
        assert cmd in text, f"README does not document {cmd}"


def test_readme_documents_menu_and_mcp_residual():
    text = README.read_text(encoding="utf-8")
    assert "/jiranator:menu" in text
    assert "createJiraIssue" in text  # residual Atlassian MCP dependency
    assert "~/.claude/.sct/jiranator/" in text  # storage location
