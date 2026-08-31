from pathlib import Path
import sys

import pytest

LIB = Path(__file__).resolve().parent.parent / "lib"
sys.path.insert(0, str(LIB))
import config  # noqa: E402


def test_load_config_neutral_default_profile():
    example = (
        Path(__file__).resolve().parent.parent / "config" / "jiranator.example.yaml"
    )
    cfg = config.load_config(example)
    assert cfg.instance_url == "https://your-org.atlassian.net"
    assert cfg.project_keys == ["PROJ"]
    assert cfg.field_ids["story_points"] == ""
    assert cfg.story_points_field_confirmed is False
    assert cfg.jql["my_open"].startswith("assignee = currentUser()")
    assert cfg.profile == "default"


def test_config_dir_resolves_under_sct(tmp_path):
    got = config.config_dir({"CLAUDE_CONFIG_DIR": str(tmp_path)})
    assert got == tmp_path / ".sct" / "jiranator" / "config"


def test_config_dir_trims_configured_root(tmp_path):
    got = config.config_dir({"CLAUDE_CONFIG_DIR": f"  {tmp_path}  "})
    assert got == tmp_path / ".sct" / "jiranator" / "config"


def test_data_dir_resolves_under_sct(tmp_path):
    got = config.data_dir({"CLAUDE_CONFIG_DIR": str(tmp_path)})
    assert got == tmp_path / ".sct" / "jiranator" / "data"


def test_ensure_data_dir_creates_idempotently(tmp_path):
    env = {"CLAUDE_CONFIG_DIR": str(tmp_path)}
    first = config.ensure_data_dir(env)
    assert first.is_dir()
    # second call must not raise and must return the same path
    second = config.ensure_data_dir(env)
    assert second == first == tmp_path / ".sct" / "jiranator" / "data"


def test_ensure_data_dir_is_owner_only(tmp_path):
    import stat

    d = config.ensure_data_dir({"CLAUDE_CONFIG_DIR": str(tmp_path)})
    assert stat.S_IMODE(d.stat().st_mode) == 0o700


def test_missing_credentials_raises():
    with pytest.raises(config.MissingCredentialsError):
        config.load_credentials({})


@pytest.mark.parametrize(
    "contents",
    [
        'instance_url "https://example.invalid"\n',
        'project_keys: "PROJ"\n',
        'field_ids: "story_points"\n',
        'jql: "my_open"\n',
        'field_ids:\n  : "customfield_10016"\n',
        'field_ids:\n  story_points:\n    id: "customfield_10016"\n',
    ],
)
def test_load_config_rejects_unsupported_shapes(tmp_path, contents):
    path = tmp_path / "jiranator.yaml"
    path.write_text(contents, encoding="utf-8")

    with pytest.raises(config.ConfigError):
        config.load_config(path)


def test_templates_dir_resolves_under_config(tmp_path):
    got = config.templates_dir({"CLAUDE_CONFIG_DIR": str(tmp_path)})
    assert got == tmp_path / ".sct" / "jiranator" / "config" / "templates"


def test_ensure_config_dir_seeds_templates(tmp_path):
    env = {"CLAUDE_CONFIG_DIR": str(tmp_path)}
    config.ensure_config_dir(env)
    tdir = config.templates_dir(env)
    for name in ("epic", "story", "task", "research", "bug"):
        assert (tdir / f"{name}.md").is_file()
    # The seeded story template carries the round-trip-safe h3 + TODO structure.
    assert "### Description" in (tdir / "story.md").read_text(encoding="utf-8")


def test_ensure_config_dir_preserves_user_edited_template(tmp_path):
    tdir = tmp_path / ".sct" / "jiranator" / "config" / "templates"
    tdir.mkdir(parents=True)
    (tdir / "story.md").write_text("### My custom section\n", encoding="utf-8")

    config.ensure_config_dir({"CLAUDE_CONFIG_DIR": str(tmp_path)})

    assert (tdir / "story.md").read_text(encoding="utf-8") == "### My custom section\n"


def test_ensure_config_dir_preserves_existing_example(tmp_path):
    seed = tmp_path / ".sct" / "jiranator" / "config" / "jiranator.example.yaml"
    seed.parent.mkdir(parents=True)
    seed.write_text("profile: private\n", encoding="utf-8")

    config.ensure_config_dir({"CLAUDE_CONFIG_DIR": str(tmp_path)})

    assert seed.read_text(encoding="utf-8") == "profile: private\n"
