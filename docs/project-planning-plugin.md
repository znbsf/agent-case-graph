# Project planning plugin (local alpha)

ACG can now provide a repository's current context to an agent, which authors a
goal-specific plan and checks it against that context. This complements the
existing append-only execution ledger. It does not require a model API key.

The plugin packages a Skill workflow and six read-only MCP tools. This follows
the current [OpenAI plugin packaging format](https://developers.openai.com/plugins/build/plugins)
and uses the [official MCP Python SDK](https://py.sdk.modelcontextprotocol.io/).
The package is for local development; installing it in a desktop host and public
publication remain separate validation steps.

## Try the CLI

The core inspection and planning commands require Python 3.11+ and Git; they have
no third-party runtime dependencies. Run from the repository root:

```powershell
python -m agent_case_graph inspect-project . --output .artifacts/project-profile.json
python -m agent_case_graph plan-project . --goal "Improve project planning and MCP integration" --output .artifacts/planning-context.json
python -m agent_case_graph check-plan . .artifacts/proposed-plan.json
```

The agent writes `proposed-plan.json` using the contract in the planning packet
or [the packaged Skill](../plugins/acg-project-planner/skills/plan-project/SKILL.md).
`check-plan` exits 0 for a valid proposal, 1 for a rejected proposal and 2 for
invalid inputs. `--output` writes an explicit JSON artifact; without it, results
go to stdout. Keep generated context and proposals outside tracked public files
when they describe a private project.

## Connect the local MCP server

Install the optional SDK in an isolated environment:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[mcp]"
.\.venv\Scripts\acg.exe mcp --workspace-root .
```

The last command waits for a host on stdin; it does not open a port. Configure
the host to launch the installed `acg` executable with arguments
`["mcp", "--workspace-root", "ABSOLUTE_REPOSITORY_ROOT"]`. Use an absolute executable
path if the virtual environment's `acg` is not on the host's PATH.

For example, a Codex MCP configuration (replace both paths before using):

```toml
[mcp_servers.acg_project]
command = "C:/path/to/agent-case-graph/.venv/Scripts/acg.exe"
args = ["mcp", "--workspace-root", "C:/path/to/target-project"]
```

The [portable plugin](../plugins/acg-project-planner/plugin.json) declares
`acg mcp`. Its operator must install `acg` with the `mcp` extra, make the executable
available on the host's PATH and forward `ACG_WORKSPACE_ROOT` into the server's
environment. The server refuses startup without an explicit workspace binding.
For a host that does not forward that variable, use the explicit launch
configuration above. The repo's `.agents/plugins/marketplace.json` makes the
package available to local marketplace discovery; adding that file does not
enable or install the plugin. Public web distribution needs a hosted integration
and review; a local stdio server alone does not provide remote repository access.

| Tool | Result |
| --- | --- |
| `acg_inspect_project` | Current repository profile, sources and static imports |
| `acg_query_project` | Path subtree or exact Python module, one-hop static imports and snapshot-bound pages |
| `acg_prepare_plan` | Goal, current profile, evidence gaps and proposal contract |
| `acg_check_plan` | Freshness, source references, targets, acceptance criteria and DAG checks |
| `acg_runtime_advice` | Existing gated runtime advice from an explicit workspace ledger |
| `acg_review_plan` | Latest linked receipts, output integrity, freshness, dependency gaps and revision hints |

## What the repository profile establishes

Inventory uses `git ls-files --cached --others --exclude-standard`, then excludes
dependency/build directories and common credential paths, including `.env`, keys
and `secrets/`. Symlinks and Windows reparse points are not read. It supports Git
worktrees, detached HEAD and repositories without a commit. No Git diff, history
body, tool log or raw ledger is included in the general profile. Git's configured
fsmonitor is disabled per inspection command so it cannot execute repository hooks.

The profile reads up to 400 eligible text/code/configuration files, 256 KB per
file and 4 MB total. Every inspected file has a SHA-256 source reference. Skipped
inputs and limits are explicit. The snapshot hash covers inspected content,
inventory, HEAD, branch and worktree status; it does not cover excluded inputs.
This is a sequential filesystem observation, not an atomic filesystem snapshot.

Python AST parsing extracts top-level symbols and explicit local import
statements, including relative imports and `src/` layouts. Ambiguous module names
do not create an import edge. These edges are static references, not execution
causality. Python, Node and Rust manifests provide declared package information;
other recognized manifests remain explicit parse gaps. Documentation supplies
bounded excerpts and declared test commands. Commands are never executed.

JavaScript source inventory includes `.js`, `.jsx`, `.cjs` and `.mjs`; CommonJS
and ESM check scripts therefore receive source IDs and content hashes. HTML/CSS
remain hashed configuration inputs. Only Python has the static import map;
these file observations do not infer JavaScript dependencies or execute checks.

`plan-project` adds evidence checks and literal goal-term path matches. It does
not claim semantic search, architectural understanding or optimal planning; the
host agent reads the context and authors the actual proposal. This allows the
same deterministic tools to work with different agents without adding a model
service to ACG.

## Query a smaller module context

```powershell
python -m agent_case_graph query-project . --module agent_case_graph.planning --page-size 3
python -m agent_case_graph query-project . --path tests --no-neighbors --page-size 10
```

Use either an exact workspace-relative POSIX file/directory path or an exact
dotted Python module name; omit both to page through the inspected files.
Paths match a complete component (`pkg` includes `pkg/`, not `pkg_extra`).
Use the filesystem's canonical path spelling; Windows case aliases are rejected
explicitly instead of returning an incorrect empty result. Unicode Python module
identifiers are supported.
Ambiguous Python module names require selecting the actual file path.
Optional neighbors include incoming and outgoing Python static imports, one hop
from the direct selection. They are not semantic test coverage for other languages.

The response supplies `items`, hash-bound `sources`, `source_snapshot_sha256`
and `pagination.next_cursor`. Pass that cursor with **identical** path/module,
neighbor option and page size to continue. The stable order is POSIX file path;
page sizes are 1–50. A content or inventory change invalidates the cursor,
including edits that keep the same Git dirty status. Requery and reassess any plan
after a stale-cursor error. Malformed cursors and invalid offsets are rejected.
The CLI returns exit 2 for invalid inputs; MCP returns a tool error.

Relationships appear on the importing file's page; their target files can be on
other pages. `inspection_scope` preserves the whole profile's file/byte limits,
counts, truncation and skip reasons on every page. An empty page or the last page
does not establish absence outside this scope. Pagination reduces returned
context; it recomputes the bounded full profile for each request and does not
extend the existing 400-file budget or provide an atomic filesystem snapshot.
The full `plan-project` proposal contract and all existing plan/evidence gates
remain applicable. Neither paging nor a passing command authorizes execution.

Shared workspace-path validation rejects trailing dots/spaces in any component,
which can alias excluded paths on Windows. Excessively nested JSON is reported as
a manifest parse gap, invalid receipt evidence or a controlled ledger/proposal error.

## Proposal and execution boundaries

`project-plan-0.1` requires a current `source_snapshot_sha256`, a goal and 1–12
tasks. Each task has an ID, title, exact existing source IDs, workspace-relative
target paths, dependencies and observable acceptance criteria. New target files
are allowed as proposals; source citations must already exist. Dependencies must
refer to unique task IDs and form a DAG. A content change invalidates a proposal
even when Git's dirty status remains the same.

A passing result is `valid_proposal` with `execution_authorized=false`. It does
not prove that the task text follows from its citations, that its acceptance
criteria are sufficient, or that execution is approved. Review remains necessary.
Static inspection does not automatically add a plan or import edges to the
canonical graph. The explicit `record-project-plan` command adds proposal nodes.

Optional ledgers are explicitly selected within the bound root, limited to 4 MB,
and projected through the existing lint, runtime readiness and Claim gates. The
adapter does not modify their bytes. Explicit ledger and receipt paths may be
under `.artifacts/`; the general inspection and proposal target policy still
excludes that directory. Ledger-specific evidence is returned under
`runtime`, separate from static repository observations.

## Record a plan, check it and revise it

The three session commands connect planning to actual execution evidence. Start
with a live Case ledger and a fresh, authored proposal. Keep `.artifacts/`
ignored by Git before capturing command output:

```powershell
acg init-case --ledger .artifacts/project-loop/events.jsonl --case-id project-loop --title "Project improvement" --run-id run:project-loop
acg record-project-plan . .artifacts/proposed-plan.json --ledger .artifacts/project-loop/events.jsonl --plan-id plan:v1 --run-id run:project-loop
acg run-plan-check . --ledger .artifacts/project-loop/events.jsonl --plan-id plan:v1 --task-id task-1 --criterion 1 --command python -m unittest discover -s tests -q
acg review-project-plan . --ledger .artifacts/project-loop/events.jsonl --plan-id plan:v1
```

Use the actual task ID and a 1-based acceptance criterion index. `--command`
must come last and takes explicitly supplied argv with `shell=False`; no command
is selected from repository text. This is an operator-selected local execution
entry point, outside the read-only MCP adapter. The caller must already have
authorization for that command. It does not dispatch runtime-managed nodes or
create Approval records. The CLI exits 0 for exit-zero checks, 1 for failed,
timed-out, output-limited or unlaunchable checks, and 2 for invalid inputs or a
refused ledger write.

Plans remain immutable proposals. Their Action nodes have
`runtime_managed=false`; AcceptanceCriterion nodes stay pending. A batch commits
the Plan, tasks, criteria and relationships together under the ledger lock,
checking both sequence and exact source SHA-256. A stale writer or invalid batch
cannot append a partial plan.

`run-plan-check` records argv, environment, start/end times, actual exit code,
repository snapshots and a hashed local receipt/output file. Its generated files
must live in an explicitly selected, ignored `.artifacts/` directory. The default
timeout is 60 seconds, configurable from 1 to 300. Captured output is limited to
1 MB; a polling monitor terminates the direct child after observing excess
output or timeout. Temporary spooling can exceed that budget between polls.
This runner does not supervise descendant processes; use finite verification
commands. A concurrent ledger edit refuses the append after execution and
preserves the receipt. Inspect it instead of blindly retrying the command.

Feedback checks `verified_by`, `checks`, `invokes` and `produces` relationships,
the recorded command identity, exclusively live provenance, receipt/output
hashes, repository freshness and the latest receipt for each criterion. A newer
failure or damaged receipt never falls back to an older success. Changes during
or after a passing command make its evidence stale. Freshness conservatively
covers the full inspected repository, including unrelated inspected files;
ignored inputs remain outside the snapshot. Dependency gaps propagate across
tasks regardless of presentation order.

Statuses include `missing_evidence`, `check_failed`, `invalid_evidence`,
`stale_evidence` and `check_passed`. All checks passing produces `checks_passed`
with `acceptance_assessed=false`: exit zero proves only the supplied command's
result. Hash checks establish recorded file integrity, not signed execution
attestation. The agent still reviews whether the checks cover the task and
whether the acceptance criteria are satisfied.

When results change the plan, collect fresh context and author a new proposal:

```powershell
acg record-project-plan . .artifacts/revised-plan.json --ledger .artifacts/project-loop/events.jsonl --plan-id plan:v2 --run-id run:project-loop --supersedes plan:v1 --evidence-node RECEIPT_NODE_ID_FROM_THE_PREVIOUS_CHECK
```

`--evidence-node` can repeat. Each ID must reference an intact, explicitly linked
check receipt from the superseded plan; `informs` edges preserve the reason for
revision. The previous plan must be active in the same live Run. New revisions
do not inherit check results. Use `acg_review_plan` from the plugin to inspect
feedback; it performs no writes or execution.

## Verification and next gates

Run the core suite without MCP to confirm that the optional dependency stays
optional. Run it again with the extra to exercise actual SDK and stdio behavior:

```powershell
python -m unittest discover -s tests -q
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
python -m compileall -q agent_case_graph scripts
```

Synthetic repository tests cover source changes, malformed proposals, missing
citations, cycles, traversal, budgets, worktrees, invalid manifests and no command
execution. SDK tests exercise structured tools, a real stdio subprocess with a
session handshake, stale
proposal rejection, invalid-ledger rejection and unchanged ledger bytes.

Session tests also cover actual commands, damaged/disconnected receipts, stale
results, criterion/dependency gaps, explicit revisions, atomic writes, concurrent
changes, output limits and timeouts. A local trial in this repository records a
real failed regression check, its repair and a plan revision based on that receipt.
This establishes the local feedback loop, not improved planning quality.

The next product gates are a host-installed plugin trial and a comparison of plan quality
and context cost across multiple real repositories. Existing browser projections
remain independently testable; successful MCP tests do not validate their UX.
