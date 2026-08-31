import os
import subprocess
import sys
from pathlib import Path

import pytest

CLI = Path(__file__).resolve().parent.parent / "cli" / "jiranator.py"


def test_cli_print_config_uses_profile_not_hardcoded(tmp_path):
    env = {**os.environ, "CLAUDE_CONFIG_DIR": str(tmp_path)}
    env.pop("JIRA_API_TOKEN", None)
    env.pop("JIRA_EMAIL", None)
    r = subprocess.run(
        [sys.executable, str(CLI), "--print-config"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert r.returncode == 0, r.stderr
    assert "your-org.atlassian.net" in r.stdout  # from seeded default profile
    assert "credentials: missing" in r.stdout  # no creds vendored
    assert "customfield_10016" not in r.stderr  # no crash path leaking


def test_cli_prefers_private_user_config(tmp_path):
    config_dir = tmp_path / ".sct" / "jiranator" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "jiranator.yaml").write_text(
        'profile: private\ninstance_url: "https://private.invalid"\n',
        encoding="utf-8",
    )
    env = {**os.environ, "CLAUDE_CONFIG_DIR": str(tmp_path)}
    env.pop("JIRA_API_TOKEN", None)
    env.pop("JIRA_EMAIL", None)

    r = subprocess.run(
        [sys.executable, str(CLI), "--print-config"],
        capture_output=True,
        text=True,
        env=env,
    )

    assert r.returncode == 0, r.stderr
    assert "instance_url: https://private.invalid" in r.stdout
    assert "profile: private" in r.stdout
    assert "your-org.atlassian.net" not in r.stdout


def test_cli_reports_present_credentials_without_exposing_values(tmp_path):
    env = {
        **os.environ,
        "CLAUDE_CONFIG_DIR": str(tmp_path),
        "JIRA_EMAIL": "email-marker",
        "JIRA_API_TOKEN": "token-marker",
    }

    r = subprocess.run(
        [sys.executable, str(CLI), "--print-config"],
        capture_output=True,
        text=True,
        env=env,
    )

    assert r.returncode == 0, r.stderr
    assert "credentials: present" in r.stdout
    assert "email-marker" not in r.stdout + r.stderr
    assert "token-marker" not in r.stdout + r.stderr


def test_cli_download_fails_loud_without_credentials(tmp_path):
    env = {**os.environ, "CLAUDE_CONFIG_DIR": str(tmp_path)}
    env.pop("JIRA_EMAIL", None)
    env.pop("JIRA_API_TOKEN", None)
    r = subprocess.run(
        [sys.executable, str(CLI), "download", "--jql", "project = X"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert r.returncode != 0
    assert "JIRA_EMAIL" in r.stderr or "credentials" in r.stderr.lower()
    assert "Traceback" not in r.stderr


def test_cli_download_requires_user_config(tmp_path):
    # Credentials present but only the seeded example exists (no jiranator.yaml):
    # download must refuse rather than authenticate against the placeholder host.
    env = {
        **os.environ,
        "CLAUDE_CONFIG_DIR": str(tmp_path),
        "JIRA_EMAIL": "email-marker",
        "JIRA_API_TOKEN": "token-marker",
    }
    r = subprocess.run(
        [sys.executable, str(CLI), "download", "--jql", "project = X"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert r.returncode == 1
    assert "jiranator.yaml" in r.stderr
    assert "Traceback" not in r.stderr


def test_cli_download_rejects_placeholder_instance_url(tmp_path):
    config_dir = tmp_path / ".sct" / "jiranator" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "jiranator.yaml").write_text(
        'instance_url: "https://your-org.atlassian.net"\n', encoding="utf-8"
    )
    env = {
        **os.environ,
        "CLAUDE_CONFIG_DIR": str(tmp_path),
        "JIRA_EMAIL": "email-marker",
        "JIRA_API_TOKEN": "token-marker",
    }
    r = subprocess.run(
        [sys.executable, str(CLI), "download", "--jql", "project = X"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert r.returncode == 1
    assert "placeholder" in r.stderr
    assert "Traceback" not in r.stderr


def test_cli_download_reports_malformed_config_without_traceback(tmp_path):
    config_dir = tmp_path / ".sct" / "jiranator" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "jiranator.yaml").write_text("- broken\n", encoding="utf-8")
    env = {
        **os.environ,
        "CLAUDE_CONFIG_DIR": str(tmp_path),
        "JIRA_EMAIL": "email-marker",
        "JIRA_API_TOKEN": "token-marker",
    }
    r = subprocess.run(
        [sys.executable, str(CLI), "download", "--jql", "project = X"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert r.returncode == 1
    assert "Error:" in r.stderr
    assert "Traceback" not in r.stderr


def _enhance_env(tmp_path, instance_url="https://real.atlassian.net"):
    """A config dir with a real (non-placeholder) user config plus creds env."""
    config_dir = tmp_path / ".sct" / "jiranator" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "jiranator.yaml").write_text(
        f'profile: default\ninstance_url: "{instance_url}"\n', encoding="utf-8"
    )
    return {
        **os.environ,
        "CLAUDE_CONFIG_DIR": str(tmp_path),
        "JIRA_EMAIL": "email-marker",
        "JIRA_API_TOKEN": "token-marker",
    }


@pytest.fixture
def cli_mod():
    """Import the CLI module in-process (conftest puts cli/ on sys.path)."""
    import jiranator

    return jiranator


def _install_fake_transport(monkeypatch, cli_mod, issue, recorder):
    """Monkeypatch the enrich seam so no network is touched: fetch returns a
    canned issue and update records its call. Also stub JiraHttp so client
    construction never matters."""
    import enhance_rest
    import jira_http

    monkeypatch.setattr(jira_http, "JiraHttp", lambda *a, **k: object())
    monkeypatch.setattr(enhance_rest, "fetch_issue", lambda http, key: issue)

    def _fake_update(http, key, description):
        recorder.append((key, description))

    monkeypatch.setattr(enhance_rest, "update_issue_description", _fake_update)


def test_cli_enhance_dry_run_does_not_push(tmp_path, monkeypatch, capsys, cli_mod):
    env = _enhance_env(tmp_path)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    # Seed templates so select_template/enrich resolves.
    import config

    config.ensure_config_dir(env)
    issue = {"key": "PROJ-1", "fields": {"issuetype": {"name": "Story"}}}
    pushes: list = []
    _install_fake_transport(monkeypatch, cli_mod, issue, pushes)

    rc = cli_mod.main(["enhance", "PROJ-1"])

    assert rc == 0
    assert pushes == []  # no --push -> no write
    out = capsys.readouterr().out
    assert "### Description" in out  # the proposed restructuring is shown


def test_cli_enhance_push_requires_description_file(
    tmp_path, monkeypatch, capsys, cli_mod
):
    env = _enhance_env(tmp_path)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import config

    config.ensure_config_dir(env)
    issue = {"key": "PROJ-1", "fields": {"issuetype": {"name": "Story"}}}
    pushes: list = []
    _install_fake_transport(monkeypatch, cli_mod, issue, pushes)

    rc = cli_mod.main(["enhance", "PROJ-1", "--push"])

    assert rc == 1
    assert pushes == []
    assert "--description-file is required with --push" in capsys.readouterr().err


def test_cli_enhance_push_writes_reviewed_description_file(
    tmp_path, monkeypatch, capsys, cli_mod
):
    env = _enhance_env(tmp_path)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import config
    import jira_http

    config.ensure_config_dir(env)
    issue = {
        "key": "PROJ-1",
        "fields": {"issuetype": {"name": "Story"}, "description": None},
    }

    class FakeHttp:
        def __init__(self):
            self.puts = []

        def get_json(self, path, params=None):
            return issue

        def put_json(self, path, body):
            self.puts.append((path, body))

    http = FakeHttp()
    monkeypatch.setattr(jira_http, "JiraHttp", lambda *a, **k: http)
    description_file = tmp_path / "description.md"
    description_file.write_text(
        "### Description\n\nReviewed content.\n", encoding="utf-8"
    )

    rc = cli_mod.main(
        [
            "enhance",
            "PROJ-1",
            "--description-file",
            str(description_file),
            "--push",
        ]
    )

    assert rc == 0
    assert http.puts[0][0] == "/rest/api/3/issue/PROJ-1"
    assert http.puts[0][1]["fields"]["description"]["type"] == "doc"
    assert "Updated description on PROJ-1." in capsys.readouterr().out


def test_cli_enhance_requires_explicit_replace_for_existing_description(
    tmp_path, monkeypatch, capsys, cli_mod
):
    env = _enhance_env(tmp_path)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import config

    config.ensure_config_dir(env)
    issue = {
        "key": "PROJ-1",
        "fields": {
            "issuetype": {"name": "Story"},
            "description": {"type": "doc", "version": 1, "content": []},
        },
    }
    pushes: list = []
    _install_fake_transport(monkeypatch, cli_mod, issue, pushes)
    description_file = tmp_path / "description.md"
    description_file.write_text("### Description\n\nReplacement.\n", encoding="utf-8")

    rc = cli_mod.main(
        [
            "enhance",
            "PROJ-1",
            "--description-file",
            str(description_file),
            "--push",
        ]
    )

    assert rc == 1
    assert pushes == []
    assert "--replace-existing is required" in capsys.readouterr().err


def test_cli_enhance_replaces_existing_description_when_explicit(
    tmp_path, monkeypatch, cli_mod
):
    env = _enhance_env(tmp_path)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import config

    config.ensure_config_dir(env)
    issue = {
        "key": "PROJ-1",
        "fields": {
            "issuetype": {"name": "Story"},
            "description": {"type": "doc", "version": 1, "content": []},
        },
    }
    pushes: list = []
    _install_fake_transport(monkeypatch, cli_mod, issue, pushes)
    description_file = tmp_path / "description.md"
    description_file.write_text("### Description\n\nReplacement.\n", encoding="utf-8")

    rc = cli_mod.main(
        [
            "enhance",
            "PROJ-1",
            "--description-file",
            str(description_file),
            "--push",
            "--replace-existing",
        ]
    )

    assert rc == 0
    assert pushes == [("PROJ-1", "### Description\n\nReplacement.\n")]


def test_cli_enhance_refuses_when_description_changes_before_push(
    tmp_path, monkeypatch, capsys, cli_mod
):
    env = _enhance_env(tmp_path)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import config
    import jira_http

    config.ensure_config_dir(env)
    initial = {
        "key": "PROJ-1",
        "fields": {"issuetype": {"name": "Story"}, "description": None},
    }
    changed = {
        "key": "PROJ-1",
        "fields": {
            "issuetype": {"name": "Story"},
            "description": {"type": "doc", "version": 1, "content": []},
        },
    }

    class FakeHttp:
        def __init__(self):
            self.responses = [initial, changed]
            self.puts = []

        def get_json(self, path, params=None):
            return self.responses.pop(0)

        def put_json(self, path, body):
            self.puts.append((path, body))

    http = FakeHttp()
    monkeypatch.setattr(jira_http, "JiraHttp", lambda *a, **k: http)
    description_file = tmp_path / "description.md"
    description_file.write_text("### Description\n\nReviewed.\n", encoding="utf-8")

    rc = cli_mod.main(
        [
            "enhance",
            "PROJ-1",
            "--description-file",
            str(description_file),
            "--push",
        ]
    )

    assert rc == 1
    assert http.puts == []
    assert "description changed since preview" in capsys.readouterr().err


def test_cli_enhance_rejects_non_utf8_description_file(tmp_path, capsys, cli_mod):
    description_file = tmp_path / "description.md"
    description_file.write_bytes(b"\xff")

    rc = cli_mod.main(
        [
            "enhance",
            "PROJ-1",
            "--description-file",
            str(description_file),
            "--push",
        ]
    )

    assert rc == 1
    assert "could not read description file" in capsys.readouterr().err


def test_cli_enhance_rejects_placeholder_instance_url(tmp_path, monkeypatch):
    env = _enhance_env(tmp_path, instance_url="https://your-org.atlassian.net")
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    r = subprocess.run(
        [sys.executable, str(CLI), "enhance", "PROJ-1"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert r.returncode == 1
    assert "placeholder" in r.stderr
    assert "Traceback" not in r.stderr


def test_cli_enhance_fails_loud_without_credentials(tmp_path):
    config_dir = tmp_path / ".sct" / "jiranator" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "jiranator.yaml").write_text(
        'instance_url: "https://real.atlassian.net"\n', encoding="utf-8"
    )
    env = {**os.environ, "CLAUDE_CONFIG_DIR": str(tmp_path)}
    env.pop("JIRA_EMAIL", None)
    env.pop("JIRA_API_TOKEN", None)
    r = subprocess.run(
        [sys.executable, str(CLI), "enhance", "PROJ-1"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert r.returncode != 0
    assert "JIRA_EMAIL" in r.stderr or "credentials" in r.stderr.lower()
    assert "Traceback" not in r.stderr


def test_cli_convert_writes_parseable_markdown(tmp_path, monkeypatch, cli_mod):
    env = {**os.environ, "CLAUDE_CONFIG_DIR": str(tmp_path)}
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import config

    config.ensure_config_dir(env)  # seed the shared issue-type templates
    csv_path = tmp_path / "in.csv"
    csv_path.write_text(
        "project_id,issue_type,component,summary,epic_key,story_points,description\n"
        "PROJ,story,Frontend,Login Form,PROJ-100,5,Log in with email\n",
        encoding="utf-8",
    )
    out_path = tmp_path / "out.md"

    rc = cli_mod.main(["convert", "--csv", str(csv_path), "--out", str(out_path)])

    assert rc == 0
    import markdown_parser

    result = markdown_parser.parse_markdown(out_path)
    assert [t.summary for t in result.tickets] == ["Login Form"]


def test_cli_create_emits_create_plan_json(tmp_path, monkeypatch, capsys, cli_mod):
    env = {**os.environ, "CLAUDE_CONFIG_DIR": str(tmp_path)}
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    import config

    config_dir = config.ensure_config_dir(env)
    (config_dir / "jiranator.yaml").write_text(
        'field_ids:\n  story_points: "customfield_12345"\n'
        "story_points_field_confirmed: true\n",
        encoding="utf-8",
    )
    md = tmp_path / "tickets.md"
    md.write_text(
        "## Login Form\n\n```yaml\nproject_id: PROJ\nissue_type: story\n"
        "component: Frontend\nepic_key: PROJ-100\nstory_points: 5\n```\n\nBody.\n",
        encoding="utf-8",
    )

    rc = cli_mod.main(["create", "--file", str(md)])

    assert rc == 0
    import json

    plan = json.loads(capsys.readouterr().out)
    assert isinstance(plan, list)
    assert plan[0]["projectKey"] == "PROJ"
    assert plan[0]["issueTypeName"] == "Story"
    assert plan[0]["parent"] == "PROJ-100"
    assert "parent" not in plan[0]["additional_fields"]
    assert plan[0]["additional_fields"]["customfield_12345"] == 5


def test_cli_create_requires_user_config_for_story_points(
    tmp_path, monkeypatch, capsys, cli_mod
):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    md = tmp_path / "tickets.md"
    md.write_text(
        "## Login Form\n\n```yaml\nproject_id: PROJ\nissue_type: story\n"
        "component: Frontend\nstory_points: 5\n```\n\nBody.\n",
        encoding="utf-8",
    )

    rc = cli_mod.main(["create", "--file", str(md)])

    assert rc == 1
    assert "jiranator.yaml" in capsys.readouterr().err


def test_cli_create_rejects_legacy_story_points_field_without_confirmation(
    tmp_path, monkeypatch, capsys, cli_mod
):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    import config

    config_dir = config.ensure_config_dir(os.environ)
    (config_dir / "jiranator.yaml").write_text(
        'field_ids:\n  story_points: "customfield_10016"\n', encoding="utf-8"
    )
    md = tmp_path / "tickets.md"
    md.write_text(
        "## Login Form\n\n```yaml\nproject_id: PROJ\nissue_type: story\n"
        "component: Frontend\nstory_points: 5\n```\n\nBody.\n",
        encoding="utf-8",
    )

    rc = cli_mod.main(["create", "--file", str(md)])

    assert rc == 1
    assert "field_ids.story_points" in capsys.readouterr().err


def test_cli_reports_config_directory_creation_failure_without_traceback(tmp_path):
    config_root = tmp_path / "not-a-directory"
    config_root.write_text("occupied\n", encoding="utf-8")
    env = {**os.environ, "CLAUDE_CONFIG_DIR": str(config_root)}

    r = subprocess.run(
        [sys.executable, str(CLI), "--print-config"],
        capture_output=True,
        text=True,
        env=env,
    )

    assert r.returncode == 1
    assert "could not initialize config directory" in r.stderr
    assert "Traceback" not in r.stderr
