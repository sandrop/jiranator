---
description: Convert a CSV of tickets to the markdown-with-YAML creator intermediate via the jiranator CLI.
argument-hint: "[csv-path] [out-path]"
allowed-tools: Bash(python3:*), AskUserQuestion
---

# Convert CSV to Markdown

Turn a CSV of ticket rows into the markdown-with-YAML intermediate that
`/jiranator:create` consumes. The deterministic conversion lives in the plugin
CLI (`convert` subcommand); this command only resolves paths, runs the CLI, and
reports. Do not re-implement the parsing or the body templates here.

Arguments: $ARGUMENTS (optional `csv-path` then `out-path`).

## Workflow

1. **Resolve the CSV path.** Use the first argument if given; otherwise ask the
   user for the path to the source CSV.
2. **Resolve the output path.** Use the second argument if given; otherwise
   default to a timestamped file next to the CSV
   (`<csv-dir>/<YYYY-mm-dd-HHMMSS>.md`) and confirm it with the user.
3. **Run the CLI** from the plugin directory. Reject paths containing NUL or
   newline characters, then shell-quote each resolved path as one argument using
   POSIX `shlex.quote` semantics. Never interpolate a raw user-selected path
   into the shell command.
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/cli/jiranator.py" convert --csv <shell-quoted-csv-path> --out <shell-quoted-out-path>
   ```
4. **Report.** On exit 0, show the output path and remind the user they can run
   `/jiranator:create <out-path>`. On a non-zero exit, surface the CLI's
   stderr verbatim (it prints one `Error:` line per problem, each row-numbered)
   and do not invent an output file.

## CSV columns

Required (non-empty per row): `project_id`, `issue_type`, `component`,
`summary`. Optional: `epic_key`, `story_points`, `description`, plus any extra
columns (passed through into the YAML block and surfaced later as
`additional_fields`). `link_to`, `link_type`, and `epic_key: NEW` are rejected
until the creator implements relationship-key resolution.

`issue_type` must be one of `epic, story, task, research, bug`. Epics may not
carry `epic_key` or `story_points`; the converter omits those fields for epic
rows.

## What the CLI does

- Validates the required columns and per-row values, failing fast with
  `Row N: '<field>' is required but empty` messages (no partial output file).
- Renders each row as an H2 summary, a fenced `yaml` metadata block (empty
  fields shown as `field:`), and the issue-type body read from the shared
  enricher templates under `~/.claude/.sct/jiranator/config/templates/`
  (`epic.md`, `story.md`, ...), with the row `description` substituted into the
  leading section.
- Joins blocks with `---`, with no leading delimiter, so the output parses
  cleanly with the creator's markdown parser.
