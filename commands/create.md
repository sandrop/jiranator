---
description: Create Jira issues from a markdown creator file via the Atlassian MCP createJiraIssue path.
argument-hint: "[markdown-path]"
allowed-tools: Bash(python3:*), Bash(sleep:*), AskUserQuestion, mcp__plugin_atlassian_atlassian__getAccessibleAtlassianResources, mcp__plugin_atlassian_atlassian__getVisibleJiraProjects, mcp__plugin_atlassian_atlassian__createJiraIssue
---

# Create Jira Issues from Markdown

Create Jira issues from a markdown-with-YAML file (produced by
`/jiranator:convert`). The plugin CLI parses the markdown and builds the
`createJiraIssue` parameter plan deterministically; the writes go through the
Atlassian MCP `createJiraIssue` tool (creation has no REST path in this phase).
MCP is not Python-callable, so the create loop is driven here, not in the CLI.

Arguments: $ARGUMENTS (optional `markdown-path`).

## Prerequisites

The Atlassian MCP plugin must be authenticated (`/plugin atlassian`).

## Workflow

1. **Validate the MCP connection.** Call `getAccessibleAtlassianResources` and
   keep only resources with Jira scopes (`read:jira-work`, `write:jira-work`).
   If the call errors or no scoped resource remains, report the error and **stop
   immediately** - create nothing.
2. **Select the Jira site and Cloud ID.** If exactly one scoped resource
   remains, use its `id`. If more than one remains, show each resource's name,
   URL, and ID, then require the user to select one through `AskUserQuestion`.
   Never infer a site from project-key overlap. Use the selected resource's
   `id` as `cloudId` for every later call.
3. **Resolve the markdown path** from the first argument, or ask the user.
4. **Build the create plan** from the plugin CLI (preview-only, no network):
   reject paths containing NUL or newline characters, then shell-quote the
   resolved path as one argument using POSIX `shlex.quote` semantics. Never
   interpolate a raw user-selected path into the shell command.
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/cli/jiranator.py" create --file <shell-quoted-markdown-path>
   ```
   The CLI prints a JSON array, one object per ticket:
   `{projectKey, issueTypeName, summary, description, additional_fields}` plus
   top-level `parent` when the ticket has an epic key. `additional_fields`
   carries `components` and the configured `field_ids.story_points` key when
   set. `cloudId` is NOT in the plan; inject it at call time. On a non-zero
   exit, surface the CLI's row-numbered `Error:` lines and stop.
5. **Validate projects.** For each unique `projectKey`, call
   `getVisibleJiraProjects` with `cloudId`, `searchString: <projectKey>`,
   `action: "create"`. Warn and exclude tickets whose project is not found or
   not creatable.
6. **Preview.** Show a table of the tickets to be created (type, summary,
   component, epic, points) and an estimate (`~20s/ticket`, accounting for the
   MCP round-trip plus the 1.5s pause).
7. **Approve.** Ask the user to approve or cancel.
8. **Create sequentially with pacing.** For each approved ticket call
   `createJiraIssue` with `cloudId` plus the plan object's fields. Wait **1.5
   seconds** between tickets (`sleep 1.5` via Bash) to respect rate limits;
   never create in parallel. Print `Created ticket X of Y: <key>` after each. On
   a failure, log it and continue with the next ticket.
9. **Report and reconcile.** Show the created keys with links and a
   `key in (...)` JQL, then write a reconciliation summary file next to the
   input (`created-<input-stem>.md`) with the full results table, the JQL, the
   links, and any failures.

## MCP tool calls

- `getAccessibleAtlassianResources` (no params) -> validate + extract `cloudId`.
- `getVisibleJiraProjects` -> `{cloudId, searchString: <projectKey>, action: "create"}`.
- `createJiraIssue` -> `{cloudId, projectKey, issueTypeName, summary, description, additional_fields}`
  taken straight from the plan object (the CLI already capitalizes
  `issueTypeName` and shapes `additional_fields`).

## Rules

- Epics carry no `parent` or story-points field; the CLI already omits them, so
  do not re-add them. Child tickets carry `parent` as a top-level MCP argument.
- Field names can vary by instance; `parent` links a story/task to its epic.
- Any authentication or resource failure in steps 1-2 stops the run before a
  single ticket is created.
