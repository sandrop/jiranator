#!/usr/bin/env python3
"""jiranator CLI.

Config-first entry point. With no subcommand (or ``--print-config``) it seeds
the user's ``.sct`` config dir with the neutral-default profile (if absent),
loads the active profile, and reports whether REST credentials are present.
Credentials come from ``.env``-populated env vars (``JIRA_EMAIL`` /
``JIRA_API_TOKEN``); none are vendored, and ``--print-config`` never emits the
token.

The ``download`` subcommand runs the unified issue downloader: it resolves
credentials (failing loud if absent), builds a stdlib ``JiraHttp`` client, and
writes a JSON snapshot (``issues.jsonl`` + ``meta.json`` + ``download.complete``)
under ``~/.claude/.sct/jiranator/data/``. JQL is user-supplied; there are no
hardcoded filter-ID presets.

The ``convert`` and ``create`` subcommands are the creator path and touch no
network. ``convert --csv PATH`` renders a CSV of tickets into the
markdown-with-YAML intermediate (reusing the shared issue-type templates);
``create --file PATH`` parses that markdown and emits the ``createJiraIssue``
parameter plan as JSON. The MCP write loop that consumes the plan lives in the
``/jiranator:create`` slash command (the Atlassian MCP transport), not in this CLI.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parent.parent / "lib"
_COMMANDS = Path(__file__).resolve().parent.parent / "commands"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

import config  # noqa: E402


def _active_config_path(config_dir: Path) -> Path:
    """The user's ``jiranator.yaml`` if present, else the seeded neutral example."""
    user = config_dir / "jiranator.yaml"
    return user if user.exists() else config_dir / "jiranator.example.yaml"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jiranator")
    parser.add_argument(
        "--print-config",
        action="store_true",
        help="Print the resolved instance URL, profile, and credential presence.",
    )
    subparsers = parser.add_subparsers(dest="command")
    menu = subparsers.add_parser(
        "menu", help="Render a numbered menu selection's command instructions."
    )
    menu.add_argument("selection", choices=("1", "2", "3", "4"))
    menu.add_argument("--arguments", default="")
    download = subparsers.add_parser(
        "download", help="Download issues matching a JQL query as a JSON snapshot."
    )
    download.add_argument("--jql", required=True, help="User-supplied JQL query.")
    download.add_argument(
        "--label",
        action="append",
        default=[],
        help="Label recorded in the snapshot meta (repeatable).",
    )
    download.add_argument(
        "--out",
        default=None,
        help="Output dir (default: ~/.claude/.sct/jiranator/data).",
    )
    enhance = subparsers.add_parser(
        "enhance",
        help="Fetch an issue, restructure its description against its issue-type "
        "template, and (with --push) update it on Jira.",
    )
    enhance.add_argument("key", help="Issue key, e.g. PROJ-123.")
    enhance.add_argument(
        "--push",
        action="store_true",
        help="Write --description-file content back to Jira (default: dry run).",
    )
    enhance.add_argument(
        "--description-file",
        help="Reviewed markdown to preview and write instead of the template skeleton.",
    )
    enhance.add_argument(
        "--replace-existing",
        action="store_true",
        help="Allow --push to replace a nonempty Jira description.",
    )
    convert = subparsers.add_parser(
        "convert",
        help="Convert a CSV of tickets to the markdown-with-YAML creator intermediate.",
    )
    convert.add_argument("--csv", required=True, help="Path to the source CSV.")
    convert.add_argument(
        "--out", default=None, help="Output markdown path (default: stdout)."
    )
    create = subparsers.add_parser(
        "create",
        help="Build the createJiraIssue parameter plan (JSON) from a markdown file.",
    )
    create.add_argument(
        "--file", required=True, help="Path to the markdown-with-YAML file."
    )
    create.add_argument(
        "--out", default=None, help="Output JSON path (default: stdout)."
    )
    return parser


def _resolve_config_and_creds():
    """Resolve REST credentials and a real user config for a live Jira call.

    Shared by ``download`` and ``enhance``: both must authenticate against the
    user's own ``jiranator.yaml``, never the seeded example (its placeholder
    ``instance_url`` is valid https, so falling back would send the Basic-auth
    token to an unintended host). Credentials are resolved BEFORE any client is
    built so a missing-credential run fails loud with one line, not a traceback.

    Returns ``(cfg, creds, cfg_dir)`` on success, or an ``int`` exit code after
    printing a one-line error.
    """
    try:
        creds = config.load_credentials(os.environ)
    except config.MissingCredentialsError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    try:
        cfg_dir = config.ensure_config_dir(os.environ)
    except OSError as error:
        print(f"Error: could not initialize config directory: {error}", file=sys.stderr)
        return 1

    user_cfg = cfg_dir / "jiranator.yaml"
    if not user_cfg.exists():
        print(
            f"Error: no jiranator.yaml in {cfg_dir}. Copy jiranator.example.yaml "
            "to jiranator.yaml, set your instance_url, and retry.",
            file=sys.stderr,
        )
        return 1
    try:
        cfg = config.load_config(user_cfg)
    except config.ConfigError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    if "your-org.atlassian.net" in cfg.instance_url:
        print(
            "Error: instance_url is still the placeholder "
            "'https://your-org.atlassian.net'; set your real Jira URL in "
            f"{user_cfg} before continuing.",
            file=sys.stderr,
        )
        return 1
    return cfg, creds, cfg_dir


def _run_download(args: argparse.Namespace) -> int:
    resolved = _resolve_config_and_creds()
    if isinstance(resolved, int):
        return resolved
    cfg, creds, _cfg_dir = resolved

    import downloader  # noqa: E402
    import jira_http  # noqa: E402

    # Build the client and run inside one guarded block: a bad instance_url
    # (non-https) raises JiraHttpError at construction, and an unusable --out or
    # data dir raises OSError from dir creation / snapshot write. Both fail loud
    # with a one-line message rather than a traceback, matching the missing-
    # credential path above.
    try:
        out_dir = Path(args.out) if args.out else config.ensure_data_dir(os.environ)
        http = jira_http.JiraHttp(cfg, creds)
        result = downloader.download(http, args.jql, out_dir=out_dir, labels=args.label)
    except jira_http.JiraHttpError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except OSError as error:
        print(f"Error: could not write snapshot: {error}", file=sys.stderr)
        return 1

    print(f"Downloaded {result.count} issue(s) to {result.issues_path}")
    return 0


def _run_enhance(args: argparse.Namespace) -> int:
    if args.push and not args.description_file:
        print("Error: --description-file is required with --push.", file=sys.stderr)
        return 1
    if args.replace_existing and not args.push:
        print("Error: --replace-existing requires --push.", file=sys.stderr)
        return 1

    supplied_description = None
    if args.description_file:
        description_path = Path(args.description_file)
        try:
            supplied_description = description_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            print(
                f"Error: could not read description file {description_path}: {error}",
                file=sys.stderr,
            )
            return 1
        if not supplied_description.strip():
            print(
                f"Error: description file is empty: {description_path}", file=sys.stderr
            )
            return 1

    resolved = _resolve_config_and_creds()
    if isinstance(resolved, int):
        return resolved
    cfg, creds, _cfg_dir = resolved

    import enhance  # noqa: E402
    import enhance_rest  # noqa: E402
    import jira_http  # noqa: E402

    # Build the client and fetch inside one guarded block: a bad instance_url
    # raises JiraHttpError at construction, a malformed key raises ValueError,
    # and a transport failure surfaces as JiraHttpError. All fail loud with one
    # line rather than a traceback.
    try:
        http = jira_http.JiraHttp(cfg, creds)
        issue = enhance_rest.fetch_issue(http, args.key)
    except (jira_http.JiraHttpError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    templates = config.templates_dir(os.environ)
    try:
        skeleton = enhance.enrich_description(issue, templates)
    except ValueError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    proposed = supplied_description if supplied_description is not None else skeleton

    # Show the restructured description as a diff against an empty baseline. A
    # content-preserving remap of an existing description is a later (interactive)
    # step; Phase 1 restructures against the issue-type template deterministically.
    print(enhance.render_diff("", proposed, args.key))

    if not args.push:
        print(
            "Dry run: review the diff, save the final markdown, then re-run with "
            "--description-file FILE --push."
        )
        return 0

    existing_description = (issue.get("fields") or {}).get("description")
    if existing_description and not args.replace_existing:
        print(
            "Error: --replace-existing is required to replace a nonempty Jira "
            "description.",
            file=sys.stderr,
        )
        return 1

    try:
        latest_issue = enhance_rest.fetch_issue(http, args.key)
    except (jira_http.JiraHttpError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    latest_description = (latest_issue.get("fields") or {}).get("description")
    if latest_description != existing_description:
        print(
            "Error: Jira description changed since preview; retry enhance before "
            "pushing.",
            file=sys.stderr,
        )
        return 1

    # The push is the write leg. update_issue_description runs the fail-loud ADF
    # degradation guard before any network write.
    try:
        enhance_rest.update_issue_description(http, args.key, proposed)
    except (jira_http.JiraHttpError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    print(f"Updated description on {args.key}.")
    return 0


def _run_convert(args: argparse.Namespace) -> int:
    # Seed the shared issue-type templates (no credentials needed for convert),
    # then render the markdown. csv_convert wraps unreadable input and bad
    # issue-type/template lookups into CsvConvertError; writing --out is the only
    # OSError left here. Both fail loud with one line per message.
    try:
        config.ensure_config_dir(os.environ)
    except OSError as error:
        print(f"Error: could not initialize config directory: {error}", file=sys.stderr)
        return 1
    templates = config.templates_dir(os.environ)

    import csv_convert  # noqa: E402

    try:
        markdown = csv_convert.convert_csv(Path(args.csv), templates)
        if args.out:
            Path(args.out).write_text(markdown, encoding="utf-8")
    except csv_convert.CsvConvertError as error:
        for message in error.errors:
            print(f"Error: {message}", file=sys.stderr)
        return 1
    except OSError as error:
        print(f"Error: could not write markdown: {error}", file=sys.stderr)
        return 1

    if args.out:
        print(f"Wrote markdown to {args.out}")
    else:
        print(markdown)
    return 0


def _run_create(args: argparse.Namespace) -> int:
    # Preview-only: parse the markdown and emit the createJiraIssue param plan as
    # JSON. The MCP write loop lives in the /jiranator:create slash command, so no
    # network is touched here. Parse errors surface one line each; a missing or
    # non-UTF-8 file fails loud without a traceback.
    import json

    import create_plan  # noqa: E402
    import markdown_parser  # noqa: E402

    try:
        cfg_dir = config.ensure_config_dir(os.environ)
        cfg = config.load_config(_active_config_path(cfg_dir))
    except (OSError, config.ConfigError) as error:
        print(f"Error: could not load creator config: {error}", file=sys.stderr)
        return 1

    try:
        result = markdown_parser.parse_markdown(Path(args.file))
    except markdown_parser.MarkdownParseError as error:
        for message in error.errors:
            print(f"Error: {message}", file=sys.stderr)
        return 1
    except (OSError, UnicodeError) as error:
        print(f"Error: could not read markdown file: {error}", file=sys.stderr)
        return 1

    has_story_points = any(ticket.story_points is not None for ticket in result.tickets)
    if has_story_points and not (cfg_dir / "jiranator.yaml").exists():
        print(
            f"Error: create plans with story points require {cfg_dir / 'jiranator.yaml'} "
            "with field_ids.story_points configured.",
            file=sys.stderr,
        )
        return 1
    if has_story_points and not cfg.story_points_field_confirmed:
        print(
            "Error: set story_points_field_confirmed: true in jiranator.yaml "
            "after verifying field_ids.story_points for this Jira site.",
            file=sys.stderr,
        )
        return 1

    try:
        plan = create_plan.build_create_plan(
            result,
            story_points_field_id=cfg.field_ids.get("story_points", ""),
        )
    except ValueError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    payload = json.dumps(plan, indent=2)

    try:
        if args.out:
            Path(args.out).write_text(payload + "\n", encoding="utf-8")
        else:
            print(payload)
    except OSError as error:
        print(f"Error: could not write plan: {error}", file=sys.stderr)
        return 1

    if args.out:
        print(f"Wrote create plan to {args.out}")
    return 0


def _run_print_config(args: argparse.Namespace) -> int:
    try:
        cfg_dir = config.ensure_config_dir(os.environ)
    except OSError as error:
        print(f"Error: could not initialize config directory: {error}", file=sys.stderr)
        return 1
    cfg = config.load_config(_active_config_path(cfg_dir))

    try:
        config.load_credentials(os.environ)
        creds = "present"
    except config.MissingCredentialsError:
        creds = "missing"

    if args.print_config:
        print(f"instance_url: {cfg.instance_url}")
        print(f"profile: {cfg.profile}")
        print(f"credentials: {creds}")
    return 0


def _run_menu(args: argparse.Namespace) -> int:
    targets = {
        "1": "download.md",
        "2": "enrich.md",
        "3": "update.md",
        "4": "create.md",
    }
    target = _COMMANDS / targets[args.selection]
    try:
        prompt = target.read_text(encoding="utf-8")
    except OSError as error:
        print(
            f"Error: could not load menu target {target.name}: {error}", file=sys.stderr
        )
        return 1
    print(prompt.replace("$ARGUMENTS", args.arguments))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "menu":
        return _run_menu(args)
    if args.command == "download":
        return _run_download(args)
    if args.command == "enhance":
        return _run_enhance(args)
    if args.command == "convert":
        return _run_convert(args)
    if args.command == "create":
        return _run_create(args)
    return _run_print_config(args)


if __name__ == "__main__":
    raise SystemExit(main())
