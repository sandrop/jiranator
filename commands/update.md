---
description: Write a restructured description back to a Jira issue via the jiranator CLI (REST + .env).
argument-hint: "[issue-key]"
allowed-tools: Bash(python3:*), AskUserQuestion
---

# Update Jira Issue (write-back)

Write a reviewed, restructured description back to one Jira issue. This is the
write path for `/jiranator:enrich`: enrich previews, update pushes. The REST
write lives in the plugin CLI (`enhance` subcommand with `--push`); this command
only resolves the key and the reviewed file, runs the CLI, and reports.

Arguments: $ARGUMENTS (optional `issue-key`, e.g. `PROJ-123`).

## Prerequisites

Set the Jira instance URL in
`~/.claude/.sct/jiranator/config/jiranator.yaml`. REST credentials are separate:
the CLI reads `JIRA_EMAIL` and `JIRA_API_TOKEN` from the environment, e.g. from a
`.env` file. If the profile or credentials are missing the CLI fails loud;
surface its error and stop.

## Workflow

1. **Resolve the issue key** from `$ARGUMENTS`, or ask the user.
2. **Resolve the reviewed markdown.** Reviewed markdown is required before
   confirmation. Pass it via `--description-file <path>`; the CLI refuses
   `--push` without this file. Reject key and path values containing NUL or
   newline characters, then shell-quote each as one argument using POSIX
   `shlex.quote` semantics.
3. **Confirm the write.** Ask the user to approve before pushing; this mutates
   Jira.
4. **Run the CLI (write-back).**
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/cli/jiranator.py" enhance <shell-quoted-issue-key> --push --description-file <shell-quoted-path>
   ```
   Add `--replace-existing` only when the user explicitly wants to overwrite a
   nonempty Jira description; otherwise the CLI refuses to clobber existing
   content (fail-loud write path).
5. **Report.** On exit 0, confirm the issue key that was updated. On a non-zero
   exit, surface the CLI's stderr verbatim and do not claim a successful write.
