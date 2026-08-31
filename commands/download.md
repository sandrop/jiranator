---
description: Download a Jira issue snapshot from a JQL query via the jiranator CLI (REST + .env).
argument-hint: "[jql]"
allowed-tools: Bash(python3:*), AskUserQuestion
---

# Download Jira Issues

Fetch a snapshot of Jira issues matching a JQL query and store it locally. The
REST fetch and pagination live in the plugin CLI (`download` subcommand); this
command only resolves the query, runs the CLI, and reports. Do not re-implement
the fetch here.

Arguments: $ARGUMENTS (optional `jql`).

## Prerequisites

Set the Jira instance URL in
`~/.claude/.sct/jiranator/config/jiranator.yaml`. REST credentials are separate:
the CLI reads `JIRA_EMAIL` and `JIRA_API_TOKEN` from the environment, e.g. from a
`.env` file. If the profile or credentials are missing the CLI fails loud;
surface its error and stop.

## Workflow

1. **Resolve the JQL.** Use `$ARGUMENTS` if given; otherwise ask the user for the
   JQL query to run.
2. **Run the CLI.** Reject a query containing NUL or newline characters, then
   shell-quote it as one argument using POSIX `shlex.quote` semantics. Never
   interpolate a raw user-supplied query into the shell command.
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/cli/jiranator.py" download --jql <shell-quoted-jql>
   ```
3. **Report.** On exit 0, show the snapshot path. Downloads land under
   `~/.claude/.sct/jiranator/data/` by default. On a non-zero exit, surface the
   CLI's stderr verbatim and do not invent a snapshot file.
