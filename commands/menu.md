---
description: "Interactive menu for jiranator Phase 1 commands"
allowed-tools: Bash(python3:*), Bash(sleep:*), AskUserQuestion, mcp__plugin_atlassian_atlassian__getAccessibleAtlassianResources, mcp__plugin_atlassian_atlassian__getVisibleJiraProjects, mcp__plugin_atlassian_atlassian__createJiraIssue
---

# Jiranator Command Menu

Present the following numbered menu to the user and wait for their selection. Do
not run anything until the user picks a number.

```
Jiranator Commands
==================

READ / RESTRUCTURE (REST + .env)
  1. Download Issues
     Fetch a snapshot of Jira issues from a JQL query into local storage

  2. Generate Issue Template  [dry run]
     Generate a fresh issue-type template skeleton (no write)

  3. Update Issue Description  [write-back]
     Push a reviewed, restructured description back to one Jira issue

CREATE (Atlassian MCP)
  4. Create Issues from Markdown
     Create Jira issues from a markdown creator file (convert a CSV first)
```

After the user selects a number:

1. Dispatch through the deterministic plugin CLI. Shell-quote any arguments the
   user supplied as one `--arguments` value (use `''` when none were supplied)
   and surface any non-zero exit:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/cli/jiranator.py" menu <selection> --arguments <shell-quoted-arguments>
   ```
2. Follow the returned command instructions directly. The resolver loads the
   selected command from the installed plugin and substitutes the forwarded
   arguments before returning it.

The resolver maps selections as follows:

| # | Command | Transport | Prerequisite |
|---|---------|-----------|--------------|
| 1 | `/jiranator:download` | REST + `.env` | none |
| 2 | `/jiranator:enrich` | REST + `.env` | none |
| 3 | `/jiranator:update` | REST + `.env` | a reviewed description (run 2 first) |
| 4 | `/jiranator:create` | Atlassian MCP `createJiraIssue` | a markdown creator file (convert a CSV first) |

Notes:

- `enrich` (2) previews a fresh template skeleton only; Phase 1 does not preserve
  or remap the existing description. `update` (3) is the write-back path for the
  same `enhance` CLI subcommand (`--push`).
- `create` (4) expects a markdown creator file; produce one from a CSV before
  running it. If the user selects 4 without one, tell them to convert a CSV
  first, then create.

Do not infer a target without running the resolver. Do not add arguments unless
the user provides them alongside their selection.
