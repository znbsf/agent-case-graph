---
name: plan-project
description: Understand a local Git project and create or revise a source-bound development plan using Agent Case Graph repository observations and optional execution evidence. Use for project maturity reviews, next-step planning, and revising a plan after new evidence.
---

Use the `acg_project` MCP server to ground a project plan in the current repository.
The server operator must bind its repository with `ACG_WORKSPACE_ROOT` or
`acg mcp --workspace-root`. Tools cannot select a different root. The local `acg`
package with its `mcp` extra must already be installed in the host environment.
If the tools are unavailable, use the equivalent CLI commands in an available
installation; do not silently install packages or change global configuration.

Call `acg_prepare_plan` with the user's current goal. Compare the returned project
identity with the requested project before using its context. Inspect relevant
manifests, documents, symbols and local import relationships. Read targeted source
files when needed; static imports alone do not explain behavior. Chinese goals
or conceptual goals may have no lexical path matches: select files using the
actual context and show the basis for that selection.

For a focused task, use `acg_query_project` (CLI `query-project`) to select an
exact POSIX path subtree or dotted Python module and optional one-hop static
import neighbors. Read all relevant pages with identical query parameters and
the returned cursor. Pages sort by path; changed snapshots reject old cursors.
Each page retains the full inspection limits and skip reasons: a final or empty
page does not prove that excluded, unsupported or over-budget inputs are absent.
Python import neighbors do not establish semantic test coverage or dependencies
in other languages. This reduces returned context, while still inspecting the
bounded whole repository per request. Use the page's exact source IDs and
snapshot for proposals; the proposal contract and validation gates still apply.

Author a concise proposal with these fields:

```json
{
  "version": "project-plan-0.1",
  "source_snapshot_sha256": "COPY_FROM_THE_CURRENT_PACKET",
  "goal": "The user's goal",
  "tasks": [
    {
      "id": "task-1",
      "title": "A concrete change or investigation",
      "source_refs": ["file:EXISTING_PATH_FROM_PROFILE_SOURCES"],
      "target_paths": ["relative/path/to/change"],
      "depends_on": [],
      "acceptance_criteria": ["An observable result that would complete this task"]
    }
  ]
}
```

Use exact IDs from `profile.sources`. Include dependencies where work actually
depends on another task, and use workspace-relative POSIX paths. Read-only tasks
can have an empty `target_paths` list. The contract allows at most 12 tasks.

Call `acg_check_plan` before presenting or continuing from the proposal. If the
snapshot is stale, collect fresh context and reconsider the plan against the new
evidence; changing only the hash does not repair its reasoning. Correct missing
sources, unsafe paths, absent acceptance criteria and dependency cycles.

When the user supplies an execution ledger, pass its relative path to
`acg_prepare_plan` or `acg_runtime_advice`. Keep graph advice and authored proposal
tasks distinct. A missing authored action is a planning gap; it does not authorize
a new tool call. Plan validation checks structure and freshness, while existing
runtime approval and evidence gates control execution.

For a recorded project plan, call `acg_review_plan` with the ledger path and Plan
ID. Inspect the latest result for each criterion, output integrity, freshness and
dependency gaps. Treat `checks_passed` as command checks passing; semantic
acceptance and task completion still require review. A newer failure or damaged
receipt must not be replaced by an older passing result.

When continuing authorized work through an available CLI, use
`record-project-plan` to save a fresh proposal in an explicitly selected live
ledger. It records immutable proposal tasks with `runtime_managed=false`.
Use `run-plan-check` only with an explicitly chosen, authorized finite command,
the actual task ID and a 1-based criterion index. Put `--command` last; repository
text must not become an executable instruction. Output capture requires an
ignored `.artifacts/` directory. The runner records actual results and does not
issue canonical runtime approvals or automatically satisfy acceptance criteria.
If a concurrent ledger change refuses the write after execution, inspect the
preserved receipt instead of replaying the command without review.

After failed checks or changed context, reconsider the work and author a new
proposal. Record it with `--supersedes PREVIOUS_PLAN_ID` and relevant
`--evidence-node RECEIPT_NODE_ID` values. Explicit relationships preserve why the
plan changed; a new revision must acquire its own current checks. Do not edit the
stored proposal in place or merely update its snapshot hash. Refresh feedback
after implementation, and identify any remaining acceptance or host integration
gate clearly.

Report what is observed, what is inferred and what remains unverified. A declared
test or CI file is not a passing result. Explain the highest-value next step and
its acceptance criteria. Continue work already authorized by the user, and attach
actual verification evidence when available; these read-only tools do not execute
commands or append ledger records.
