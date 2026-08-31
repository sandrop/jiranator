# Changelog

## 0.6.0 - 2026-08-31

- First standalone release. `jiranator` moved out of the `sandro-claude-tooling`
  marketplace subtree into its own dev/prod repo pair, mirroring that
  marketplace's split:
  - Private `jiranator-dev` (this repo) is the source of truth: plugin source,
    the full test suite, `run_tests.sh`, and `publish.sh`. History was preserved
    via `git subtree split`, so per-file history and this changelog carry over.
  - Public `jiranator` is a marketplace-of-one: `publish.sh` vendors the
    leak-checked plugin tree (including `tests/`) to the repo root and generates
    a `.claude-plugin/marketplace.json` with `source: "./"`.
  - Install moves from `jiranator@sandro-claude-tooling` to
    `jiranator@jiranator` (`claude plugin marketplace add sandrop/jiranator`).
- No runtime behavior change: the CLI, commands, config contract, and transports
  are identical to 0.5.0.

## 0.5.0 - 2026-08-26

- Phase 1 command surface ported: the read/restructure commands now have
  plugin-namespaced slash commands over the CLI, alongside a menu.
  - `commands/download.md`: `download --jql` (REST + `.env`) into a
    local snapshot.
  - `commands/enrich.md`: `enhance <key>` dry-run issue-type template
    skeleton (no write, no content-preserving remap in Phase 1).
  - `commands/update.md`: `enhance <key> --push` write-back of a
    reviewed description.
  - `commands/menu.md`: interactive menu dispatching to the four Phase 1
    commands (download, enrich, update, create). `convert` stays a `create`
    prerequisite, not a menu entry. Its numbered handoff resolves through the
    deterministic `jiranator.py menu <selection>` CLI boundary.
  - `README.md`: new `## Commands` section documenting the slash-command surface
    and the menu.
  - Tests: `test_commands.py` (command/menu presence, frontmatter, menu
    completeness, command->CLI-subcommand mapping), `test_readme_commands.py`
    (README documents the surface + MCP residual + storage), and
    `test_no_real_jira_artifacts.py` (durable guard against non-placeholder Jira
    instance hosts in shipped code).

## 0.4.0 - 2026-08-26

- Creator path folded in: turn a CSV of tickets into new Jira issues.
  - `lib/markdown_parser.py`: stdlib port of the markdown-with-YAML parser
    (dataclasses, no pydantic/PyYAML). Adds `LinkType` to `lib/models.py`.
  - `lib/csv_convert.py`: `jiranator convert --csv PATH [--out PATH]` renders a
    CSV into the markdown intermediate, reusing the shared issue-type templates
    for each block body and failing fast with row-numbered messages.
  - `lib/create_plan.py`: `jiranator create --file PATH [--out PATH]` parses the
    markdown and emits the `createJiraIssue` parameter plan as JSON
    (preview-only, no network; `cloudId` is injected by the command).
  - `commands/convert.md` and `commands/create.md`: the
    plugin's first slash commands. `/jiranator:create` drives the Atlassian MCP
    `createJiraIssue` loop with a 1.5s pace and the
    `getAccessibleAtlassianResources` / `getVisibleJiraProjects` preflight
    (creation stays on the Atlassian MCP transport).
- The optional REST-creation spike (AC #3) is deferred out of this change; issue
  creation remains on the MCP path.
- Review hardening preserves multiline and quoted CSV scalars, rejects
  unsupported relationship markers, keeps horizontal rules inside descriptions,
  omits blank custom fields, reports non-UTF-8 input without a traceback, uses
  the configured story-points field ID, shell-quotes command paths, and permits
  the required paced `sleep` call.
- Native-review hardening resolves the CLI through `CLAUDE_PLUGIN_ROOT`, requires
  explicit Jira-site selection when MCP exposes multiple sites, refuses the
  seeded story-points placeholder, rejects surplus CSV cells and reserved field
  collisions, accepts alphanumeric Jira project keys, and fixes the positional
  create-command handoff.
- Second native-review hardening leaves the starter story-points field unset,
  maps canonical `research` tickets to `Research Spike`, rejects multiline CSV
  summaries, and fails loudly when a customized template cannot accept a CSV
  description.
- Final native-review hardening emits top-level MCP parents, requires an
  explicit story-points field confirmation for legacy configs, distinguishes
  ticket delimiters from H2 sections without YAML, and restricts CSV description
  injection to the template's leading section.

## 0.3.1 - 2026-08-25

- `enhance --push` now requires reviewed markdown from `--description-file`;
  the deterministic template skeleton remains a dry-run starting point and can
  no longer be passed directly to the write seam.
- Replacing a nonempty Jira description requires the explicit
  `--replace-existing` flag. The production CLI test now exercises the real ADF
  guard and transport PUT instead of stubbing the update function. The CLI
  re-fetches immediately before PUT and refuses a stale write if the Jira
  description changed after the preview.
- The ADF degradation guard now warns on blockquotes, table rows, and inline raw
  HTML as documented, and Jira issue-key validation accepts digits and
  underscores after the initial project-key letter.
- ADF block parsing preserves soft-wrapped prose as one paragraph, permits HTML
  examples inside supported inline-code spans, and detects multiline HTML
  comments plus GFM tables with or without outer pipes.
- Enhance fetches no longer request an instance-specific custom field, and a
  non-UTF-8 `--description-file` fails with a one-line error instead of a
  traceback. The marketplace catalog now has a regression test that keeps its
  jiranator version aligned with the package manifest.

## 0.3.0 - 2026-08-25

- Enricher folded in: `jiranator enhance KEY [--push]` fetches an issue,
  restructures its description against the correct issue-type template, shows the
  proposed description as a diff (dry run), and with `--push` writes it back to
  the existing ticket via `PUT /rest/api/3/issue/{key}` with an ADF body.
- `lib/adf.py`: stdlib markdown -> ADF converter (ported verbatim). Supports the
  locked subset (`### h3`, paragraphs, bullet/ordered lists, fenced code, inline
  code/bold/italic/links) and returns a warning per downgrade
  (`markdown_to_adf_with_warnings`).
- `lib/enhance.py`: deterministic helpers (`parse_args`, `find_todo_sections`,
  `render_diff`, `build_edit_payload`, `is_stale_write`) plus `select_template`
  and `enrich_description`. Issue-type templates are config/profile-driven:
  `select_template(issue_type, templates_dir)` reads `<issuetype>.md` from a
  per-config, user-editable templates dir instead of a hardcoded dict.
- `lib/enhance_rest.py`: `fetch_issue` / `update_issue_description` over the
  injected `HttpTransport` seam (no `requests`). `update_issue_description`
  converts markdown to ADF and refuses the push (fail loud) on ANY degradation
  warning before the PUT, including a template still carrying `<!-- TODO -->`
  markers.
- `lib/jira_http.py`: `put_json` added to the `HttpTransport` protocol and
  `JiraHttp`; it tolerates the 204 No Content empty body Jira returns on a
  description update and still maps non-2xx to `JiraHttpError`.
- `lib/config.py`: `templates_dir` helper and template seeding in
  `ensure_config_dir` (copies each packaged `<issuetype>.md` into
  `config/templates/` if absent, never clobbering a user-edited template).
- `config/templates/{epic,story,task,research,bug}.md`: neutral-default
  issue-type templates (h3 headings + `<!-- TODO -->` markers, round-trip-safe
  through the ADF converter once filled).
- Ported from the legacy `jirainator` enricher, rewritten stdlib-only (no
  `requests`, no `pydantic`). A subprocess-boundary smoke test drives the real
  fetch -> enrich -> push seam in a fresh process and asserts both the pushed ADF
  body and the fail-loud guard.

## 0.2.0 - 2026-08-24

- Phase 1 downloader: the single unified issue downloader on the unified JSON
  schema, replacing the two prior downloaders. JQL-driven and user-supplied; no
  hardcoded filter-ID presets.
- `lib/jira_http.py`: injectable stdlib HTTP seam (`JiraHttp` over
  `urllib.request` + HTTP Basic auth, redirects refused so the credential
  header never leaks). The client requires an absolute `https` `instance_url`
  and rejects any other scheme at construction, so a misconfigured `http://`
  host can never send the Basic-auth token in clear text. Covered by
  `tests/test_jira_http.py` through the injectable opener seam (request build,
  auth header, query encoding, redirect refusal, error mapping).
- `lib/downloader.py`: `extract_status_transitions` / `extract_sprint_transitions`
  (ported verbatim from downloader A), `build_record` (lossless raw
  `fields`/`changelog` from downloader B plus inline transitions), paginated
  `fetch_issues` over `POST /rest/api/3/search/jql` with `expand=changelog` and
  a full-changelog top-up on truncation, and `download` orchestrating fetch ->
  record -> persist.
- `lib/store.py`: atomic snapshot writer (`issues.jsonl` + `meta.json` staged
  via pid-suffixed `.tmp` + `os.replace`, then a `download.complete` sentinel;
  `.tmp` files are unlinked on failure). The prior sentinel is invalidated
  before either final file is replaced, so a repeat download that fails mid-way
  never leaves a mixed snapshot certified as complete. Snapshot files are
  owner-only (0600) and a freshly created output dir is 0700. Data lands under
  `$CLAUDE_CONFIG_DIR/.sct/jiranator/data/` (default `~/.claude/.sct/jiranator/data/`).
- `lib/config.py`: `data_dir` / `ensure_data_dir` siblings of the config-dir
  helpers (no seeding).
- CLI: `jiranator download --jql "..." [--label L ...] [--out DIR]`. Resolves
  credentials before building the client and fails loud (one-line message, no
  traceback) when `JIRA_EMAIL` / `JIRA_API_TOKEN` are absent, when `instance_url`
  is not https, or when the output dir / snapshot write hits a filesystem error.
  `--print-config` behavior is unchanged.
- A subprocess-boundary smoke test drives a real `download` in a fresh process
  and asserts the on-disk snapshot (`docs/patterns/subprocess-boundary-smoke.md`).

## 0.1.0 - 2026-08-24

- Phase 1 foundation: scaffold `plugins/jiranator/` and register it in the
  marketplace catalog. Mirrors the `ccu` plugin layout
  (`.claude-plugin/plugin.json`, `config/`, `lib/`, `cli/`, `tests/`).
- Config-first contract in `lib/config.py`: a frozen `JiraConfig`
  (instance_url, project_keys, field_ids, jql, profile) loaded by a stdlib-only
  flat-subset YAML parser (no PyYAML). Nothing Jira-instance-specific is
  hardcoded; the shipped `jiranator.example.yaml` is a neutral default profile.
- Credentials model: `load_credentials` reads `JIRA_EMAIL` / `JIRA_API_TOKEN`
  from the `.env`-populated environment and raises `MissingCredentialsError`
  when either is absent. Credentials are never part of `JiraConfig` and never
  vendored. Transport is REST with `.env` credentials; the Atlassian MCP is
  reserved for cases a later phase documents as REST-infeasible.
- State path: config and state resolve under `$CLAUDE_CONFIG_DIR/.sct/jiranator/`
  (default `~/.claude/.sct/jiranator/`), never a repo-local path. The CLI seeds
  the config dir with `jiranator.example.yaml` on first run
  (`mkdir -p`-style, idempotent, never clobbering an existing file).
- CLI bootstrap `cli/jiranator.py --print-config` resolves the active profile,
  reports credential presence, and emits no token. A subprocess-boundary smoke
  test asserts a clean `$CLAUDE_CONFIG_DIR` gets the dir + seed on a real run.
- Config validation rejects malformed or nested collection shapes and
  normalizes the configured root before creating state. Directory-creation
  failures return a clean CLI error; regression tests cover private config
  selection, credential redaction, and preservation of existing seed files.
