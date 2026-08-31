---
description: Generate a Jira issue-type template skeleton (dry run, no write).
argument-hint: "[issue-key]"
allowed-tools: Bash(python3:*), AskUserQuestion
---

# Generate Jira Issue Template (dry run)

Fetch one Jira issue and generate a fresh template skeleton for its issue type,
printing the proposed markdown **without writing anything back to Jira**. Phase
1 does not preserve or remap the issue's existing description. The fetch and
template logic live in the plugin CLI (`enhance` subcommand); this command only
resolves the key, runs the CLI, and reports.

Writing the result back is a separate step: `/jiranator:update`.

Arguments: $ARGUMENTS (optional `issue-key`, e.g. `PROJ-123`).

## Prerequisites

Set the Jira instance URL in
`~/.claude/.sct/jiranator/config/jiranator.yaml`. REST credentials are separate:
the CLI reads `JIRA_EMAIL` and `JIRA_API_TOKEN` from the environment, e.g. from a
`.env` file. If the profile or credentials are missing the CLI fails loud;
surface its error and stop.

## Workflow

1. **Resolve the issue key.** Use `$ARGUMENTS` if given; otherwise ask the user.
2. **Run the CLI (dry run).** Reject a key containing NUL or newline characters,
   then shell-quote it as one argument using POSIX `shlex.quote` semantics.
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/cli/jiranator.py" enhance <shell-quoted-issue-key>
   ```
   No `--push` flag: this is a preview only. It prints the template skeleton for
   review.
3. **Report.** Show the proposed template skeleton. To write it back, save the
   reviewed markdown and run `/jiranator:update <issue-key>`. On a non-zero exit,
   surface the CLI's stderr verbatim.
