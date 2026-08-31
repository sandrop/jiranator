# jiranator

Config-first Jira tooling for [Claude Code](https://docs.claude.com/en/docs/claude-code).
`jiranator` resolves everything instance-specific (instance URL, project keys,
field ids, JQL) from a profile you control, reads REST credentials from your
environment, and keeps state under `~/.claude/.sct/jiranator/`. Nothing about
your Jira instance is hardcoded, and no credentials are vendored into the plugin.

## Install

```bash
claude plugin marketplace add sandrop/jiranator
claude plugin install jiranator@jiranator
```

## Commands

Run `/jiranator:menu` for an interactive menu, or invoke a command directly:

| Command | Wraps | Transport | Purpose |
|---------|-------|-----------|---------|
| `/jiranator:menu` | menu | none | Numbered menu dispatching to the commands below |
| `/jiranator:download` | `download --jql` | REST + `.env` | Fetch a snapshot of issues from a JQL query |
| `/jiranator:enrich` | `enhance <key>` | REST + `.env` | Preview a fresh issue-type template skeleton (dry run, no write) |
| `/jiranator:update` | `enhance <key> --push` | REST + `.env` | Write a reviewed description back to one issue |
| `/jiranator:convert` | `convert --csv` | none | Turn a CSV of tickets into the markdown creator file |
| `/jiranator:create` | `create` | Atlassian MCP | Create issues from the markdown creator file |

## Configuration

State and config live under `~/.claude/.sct/jiranator/config/` (or
`$CLAUDE_CONFIG_DIR/.sct/jiranator/config/` when set), never a repo-local path.
On first run the CLI seeds a neutral `jiranator.example.yaml`; copy it to
`jiranator.yaml` and edit:

```yaml
profile: default
instance_url: "https://your-org.atlassian.net"
project_keys:
  - "PROJ"
field_ids:
  story_points: ""
story_points_field_confirmed: false
jql:
  my_open: "assignee = currentUser() AND statusCategory != Done"
```

The loader is a stdlib-only flat-subset YAML parser (no PyYAML); only the
documented shape is supported and anything malformed fails loud.

## Credentials

REST credentials come from your environment and are never stored by this plugin:

```bash
export JIRA_EMAIL="<your-atlassian-account-email>"
export JIRA_API_TOKEN="<token>"   # id.atlassian.com -> Security -> API tokens
```

A run with either variable missing reports `credentials: missing` rather than
building a half-authenticated client. The configured `instance_url` must be an
absolute `https` URL, since the API token travels in an HTTP Basic-auth header.

## License

MIT.
