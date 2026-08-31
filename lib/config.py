"""Flat-subset YAML config loader and credentials model for the jiranator plugin.

Runtime code is stdlib-only: no PyYAML. This hand-rolls the narrow YAML subset
the jiranator config uses, following the `ccu` plugin and `cobtask-common`
frontmatter-parser precedent. Only the shapes documented in
`config/jiranator.example.yaml` are supported; anything malformed raises
`ConfigError` rather than guessing.

Supported shape::

    profile: default
    instance_url: "https://your-org.atlassian.net"
    project_keys:
      - "PROJ"
    field_ids:
      story_points: ""
    story_points_field_confirmed: false
    jql:
      my_open: "assignee = currentUser() AND statusCategory != Done"

Config carries no secrets: instance URL, project keys, field ids, and JQL are
non-sensitive routing data. REST credentials are read separately from the
process environment (populated from `.env`) via `load_credentials`, never from
this file and never vendored into the repo.
"""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

# Match the ccu loader's comment convention: `#` starts a line comment. The
# neutral-default JQL carries no `#`; a value that needs one is outside this
# flat subset.
_COMMENT = "#"

# Packaged neutral-default example shipped inside the plugin tree, copied into
# the user's .sct config dir as a starter on first CLI run.
_PACKAGED_EXAMPLE = (
    Path(__file__).resolve().parent.parent / "config" / "jiranator.example.yaml"
)

# Packaged neutral-default issue-type templates shipped inside the plugin tree,
# copied per-file into the user's config `templates/` dir on first CLI run. Each
# is round-trip-safe markdown (h3 headings + `<!-- TODO -->` markers) so the
# enricher's markdown->ADF conversion stays clean once the TODOs are filled.
_PACKAGED_TEMPLATES = Path(__file__).resolve().parent.parent / "config" / "templates"


class ConfigError(Exception):
    """Raised when the config file cannot be parsed into a valid JiraConfig."""


class MissingCredentialsError(Exception):
    """Raised when JIRA_EMAIL or JIRA_API_TOKEN is absent from the environment."""


@dataclass(frozen=True)
class JiraConfig:
    instance_url: str
    project_keys: list[str]
    field_ids: dict[str, str]
    jql: dict[str, str]
    profile: str = "default"
    story_points_field_confirmed: bool = False


@dataclass(frozen=True)
class JiraCredentials:
    email: str
    api_token: str


def _unquote(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        return s[1:-1]
    return s


def load_config(path: Path) -> JiraConfig:
    """Parse the flat-subset YAML config at ``path`` into a JiraConfig.

    Unknown top-level keys are ignored (forward-compat, matching the ccu
    loader). Missing keys fall back to empty defaults. Malformed structure
    (an indented line before any key, a stray top-level list item) raises
    ConfigError rather than guessing.
    """
    try:
        # utf-8-sig strips a leading BOM so a BOM-prefixed first key still
        # parses at indent 0 instead of being misread as nested content.
        text = Path(path).read_text(encoding="utf-8-sig")
    except OSError as e:
        raise ConfigError(f"Could not read config at {path} ({e}).") from e
    except UnicodeDecodeError as e:
        raise ConfigError(f"Config at {path} is not valid UTF-8 ({e}).") from e

    profile = "default"
    story_points_field_confirmed = False
    instance_url = ""
    project_keys: list[str] = []
    field_ids: dict[str, str] = {}
    jql: dict[str, str] = {}

    # None = no section yet; "ignore" = inside an unknown/scalar block whose
    # nested content is skipped; otherwise the active list/map container key.
    section: str | None = None

    for raw_line in text.splitlines():
        line = raw_line.split(_COMMENT, 1)[0].rstrip()
        if not line.strip():
            continue

        indent = len(line) - len(line.lstrip())
        stripped = line.strip()

        if indent == 0:
            if stripped.startswith("- "):
                raise ConfigError(f"Unexpected top-level list item: {raw_line!r}")
            key, separator, value = stripped.partition(":")
            key = key.strip()
            value = value.strip()
            if not separator or not key or any(char.isspace() for char in key):
                raise ConfigError(f"Malformed top-level entry: {raw_line!r}")
            if key == "profile":
                section = "ignore"
                if value:
                    profile = _unquote(value)
            elif key == "instance_url":
                section = "ignore"
                if value:
                    instance_url = _unquote(value)
            elif key == "story_points_field_confirmed":
                section = "ignore"
                normalized = _unquote(value).lower()
                if normalized not in ("true", "false"):
                    raise ConfigError(
                        "story_points_field_confirmed must be true or false"
                    )
                story_points_field_confirmed = normalized == "true"
            elif key == "project_keys":
                if value:
                    raise ConfigError(f"Malformed project_keys entry: {raw_line!r}")
                section = "project_keys"
            elif key == "field_ids":
                if value:
                    raise ConfigError(f"Malformed field_ids entry: {raw_line!r}")
                section = "field_ids"
            elif key == "jql":
                if value:
                    raise ConfigError(f"Malformed jql entry: {raw_line!r}")
                section = "jql"
            else:
                section = "ignore"  # unknown key: skip its block
            continue

        # Indented line belongs to the current section.
        if section is None:
            raise ConfigError(f"Unexpected indented line before any key: {raw_line!r}")
        if section in ("project_keys", "field_ids", "jql") and indent != 2:
            raise ConfigError(f"Unsupported nesting in {section}: {raw_line!r}")
        if section == "project_keys":
            if not stripped.startswith("- "):
                raise ConfigError(f"Malformed project_keys entry: {raw_line!r}")
            project_keys.append(_unquote(stripped[2:]))
        elif section in ("field_ids", "jql"):
            k, sep, v = stripped.partition(":")
            if not sep or not k.strip():
                raise ConfigError(f"Malformed {section} entry: {raw_line!r}")
            target = field_ids if section == "field_ids" else jql
            target[k.strip()] = _unquote(v.strip())
        # else: indented content under an ignored/unknown key -> skip

    return JiraConfig(
        instance_url=instance_url,
        project_keys=project_keys,
        field_ids=field_ids,
        jql=jql,
        profile=profile,
        story_points_field_confirmed=story_points_field_confirmed,
    )


def load_credentials(env: Mapping[str, str]) -> JiraCredentials:
    """Read REST credentials from a `.env`-populated environment mapping.

    Raises MissingCredentialsError when either JIRA_EMAIL or JIRA_API_TOKEN is
    absent or empty, so a missing-credential run fails loud instead of building
    a half-authenticated client.
    """
    email = (env.get("JIRA_EMAIL") or "").strip()
    token = (env.get("JIRA_API_TOKEN") or "").strip()
    if not email or not token:
        raise MissingCredentialsError(
            "JIRA_EMAIL and JIRA_API_TOKEN must both be set (populate them from "
            "your .env); neither is vendored into the plugin."
        )
    return JiraCredentials(email=email, api_token=token)


def config_dir(env: Mapping[str, str]) -> Path:
    """The jiranator config dir under the `.sct` plugin slot.

    ``$CLAUDE_CONFIG_DIR`` if set, else ``~/.claude``; never a repo-local path.
    """
    root = (env.get("CLAUDE_CONFIG_DIR") or "").strip() or "~/.claude"
    return Path(root).expanduser() / ".sct" / "jiranator" / "config"


def templates_dir(env: Mapping[str, str]) -> Path:
    """The issue-type templates dir under the jiranator config dir.

    Child of :func:`config_dir` (``.../config/templates``). ``select_template``
    reads ``<issuetype>.md`` from here; it is per-config and user-editable, which
    is what makes the enricher's templates config/profile-driven rather than
    hardcoded.
    """
    return config_dir(env) / "templates"


def data_dir(env: Mapping[str, str]) -> Path:
    """The jiranator snapshot-data dir under the `.sct` plugin slot.

    Sibling of :func:`config_dir` (``.../.sct/jiranator/data``). ``$CLAUDE_CONFIG_DIR``
    if set, else ``~/.claude``; never a repo-local path.
    """
    root = (env.get("CLAUDE_CONFIG_DIR") or "").strip() or "~/.claude"
    return Path(root).expanduser() / ".sct" / "jiranator" / "data"


def ensure_data_dir(env: Mapping[str, str]) -> Path:
    """Create the snapshot-data dir if absent and return it.

    Idempotent (``mkdir -p``-style). Unlike :func:`ensure_config_dir` it seeds
    nothing; snapshots are written into it by the downloader. The dir is forced
    to 0700: it holds raw Jira snapshots, and because this pre-creates the dir
    the store's own create-time 0700 would otherwise be skipped on the default
    path, leaving a 0755 dir under a 022 umask.
    """
    d = data_dir(env)
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    return d


def ensure_config_dir(env: Mapping[str, str]) -> Path:
    """Create the config dir, seed ``jiranator.example.yaml``, and seed the
    issue-type templates, each only if absent.

    Idempotent (``mkdir -p``-style). Never clobbers an existing example, the
    user's ``jiranator.yaml``, or a user-edited template file. Returns the dir.
    """
    d = config_dir(env)
    d.mkdir(parents=True, exist_ok=True)
    seed = d / "jiranator.example.yaml"
    if not seed.exists():
        if _PACKAGED_EXAMPLE.exists():
            shutil.copy2(_PACKAGED_EXAMPLE, seed)
        else:
            # A missing packaged example means a broken/incomplete install, not
            # a normal state. Say so loudly instead of leaving an empty config
            # dir with no diagnostic.
            print(
                f"Warning: packaged example config not found at "
                f"{_PACKAGED_EXAMPLE}; config dir created without a starter "
                "jiranator.example.yaml (broken install?).",
                file=sys.stderr,
            )
    _seed_templates(d)
    return d


def _seed_templates(config_dir_path: Path) -> None:
    """Copy each packaged ``<issuetype>.md`` into ``<config>/templates`` if absent.

    Never clobbers a user-edited template (the ``select_template`` contract lets
    users customize these). A missing packaged templates dir is a broken install;
    warn loudly rather than leaving the enricher with no templates to select.
    """
    tdir = config_dir_path / "templates"
    tdir.mkdir(parents=True, exist_ok=True)
    if not _PACKAGED_TEMPLATES.is_dir():
        print(
            f"Warning: packaged templates not found at {_PACKAGED_TEMPLATES}; "
            "templates dir created without seeded issue-type templates (broken "
            "install?).",
            file=sys.stderr,
        )
        return
    for src in sorted(_PACKAGED_TEMPLATES.glob("*.md")):
        dest = tdir / src.name
        if not dest.exists():
            shutil.copy2(src, dest)
