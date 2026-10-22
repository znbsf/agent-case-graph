# Agent Case Graph architecture

## 1. Product boundary

ACG is an evidence-first trace protocol, not a drawing engine. The durable layer records what happened and what relations were explicitly declared. Rendering remains replaceable.

```text
Event Ledger -> Canonical Graph -> graph.html
```

## 2. Durable layer

The append-only ledger has four event kinds:

```text
graph.declared
node.recorded
edge.recorded
state.changed
```

Every event has a stable `event_id`, contiguous `sequence`, actor and provenance. `capture_mode` is always one of `live / reconstructed / synthetic`.

The canonical graph retains stable IDs, typed nodes and typed edges. Runtime gates and lint consume this graph; no renderer is allowed to infer causality from coordinates or timestamps.

## 3. View

`renderer.py` writes one self-contained `graph.html`: a layered top-down layout where a node sits one row below its deepest earlier predecessor (ledger order breaks cycles) and columns follow ledger order. Every canonical node and edge is drawn; `contains` is dashed because it declares scope, not causality. Clicking a node shows its attrs, incoming/outgoing edges, event IDs and source refs. The page has no CDN dependency, uses a restrictive CSP and never executes an Action.

## 4. Relation policy

Only authored canonical edges, or display summaries carrying exact authored
edge witnesses, are rendered. The following styling/ranking policy applies to
the static/legacy renderer; it does not establish verified causality.

- solid: forward workflow or dependency relations such as `frames`, `precedes`, `invokes`, `produces`, `targets`;
- dotted: evidence and provenance such as `supports`, `checks`, `uses`, `informs`, `derived_from`;
- scope-only: containment relations such as `contains`; they remain in node details and never affect DAG rank.

Only the forward workflow/dependency set constrains DAG rank. Evidence and
provenance relations remain authored facts, but they are reviewed in the HTML
Evidence tab and node details rather than fed back into the workflow topology.
This prevents a valid claim-to-evidence audit loop from turning the main graph
into a false one-node-per-rank chain.

The renderer never creates a missing support path from node types. A final Claim without explicit support remains visibly incomplete and is handled by lint.

### Graph-only workflow inference

The optional inference pass consumes the canonical graph, not the source
conversation. `frames` binds a Goal revision to a Plan revision; `invokes` and
`produces` recover actions and outputs; `supports` connects outputs to claims;
`informs` records visible evidence or reasoning summaries that changed a plan.
It reports semantic gaps such as a plan without goal context or a tool call
without an explicit output. It cannot reconstruct hidden reasoning or raw tool
payloads that were intentionally not modeled.

## 5. Runtime remains separate

Only explicit `runtime_managed=true` Step, Action, ToolCall and Verification nodes inside a Run (including nested `contains` scopes) enter the control plane. `next-actions` uses `precedes / blocked_by / approved_by`; `step-status` appends a checkpoint after validating the transition. Approval scope matching is exact-token based (`*`, a list, or comma/semicolon-delimited scopes), not substring matching.

An executable node's minimal context packet follows incoming context lineage for
at most three hops, so `Action <- Plan <- Goal/ReasoningSummary` is available
without loading the whole graph.

Context construction shares the snapshot's incoming/outgoing adjacency indexes.
The packet includes the selected `task` plus relevant `nodes`, whitelisted file,
input/output and acceptance references, event IDs and source references. Raw tool
payloads remain in referenced artifacts. `selected_node_count` includes the task;
`node_reduction_ratio` and its compatibility alias `context_reduction_ratio`
measure node counts only (`measurement_basis=node_count`), not tokens or quality.

All executable node types with `mutating=true` use the same gates. Approval
endpoints must actually be `Approval` nodes. A `targets` endpoint must be a
`Target`; `modifies` may point to a `Target` or `Artifact`. A missing Run capture
mode never defaults to live for mutation readiness.

State-dependent writes use optimistic concurrency: events and their SHA256 come
from the same byte snapshot, and `append_event` checks both the expected last
sequence and that digest under the ledger lock before writing. Conflicts fail
with a reload/retry error; there is no automatic retry using stale gate results.
This applies to step checkpoints, claim confirmations and recommendation
snapshots. Checkpoint IDs and attempts therefore match the accepted sequence.
Step checkpoints preserve the selected Run's declared capture mode. This guards
cooperating ledger writers; it is not an executor lease or tool idempotency layer.

The visual trace can explain runtime state but cannot declare a node Ready, grant approval or invoke tools.

### Graph-native advisory control plane

`graph-runtime-0.1` consumes the same canonical graph but remains derived and side-effect free. It returns a Ready `Action`/`ToolCall` recommendation only for an explicit runtime-managed node; it never manufactures a ToolCall from labels, timestamps, layout, or an embedding match.

For each `Claim` or `RootCause`, the claim gate follows only declared incoming `supports` / `refutes` edges. A confirmation needs at least one complete non-derived evidence node and a non-derived `supports` relation, and can be tightened with `minimum_support_count`, `required_evidence_ids`, `required_evidence_types`, and `required_capture_modes`. Claim, evidence and relation must each have one identical explicit Run owner, or all three must be global; other-Run, global-to-Run, and multi-Run inputs are excluded rather than silently shared. Pending, failed, partial, derived, or unsupported source nodes are reported as evidence gaps; usable refuting evidence blocks confirmation. `claim-status --status confirmed` stores a derived gate receipt and only infers an omitted Run when the Claim has one unique owner, while the low-level Ledger format remains able to faithfully import pre-existing reconstructed history.

`record-recommendation` records a derived `Decision` snapshot (`data_origin=derived`, `not_native_telemetry=true`) with the source Ledger hash and selected node IDs. `review-paths` later compares that snapshot with subsequent runtime node records using Ledger sequence. It labels the recommendation and comparison as derived, labels the actual side by its original capture mode, and never re-executes or invents missing actions.

### Evidence completion states

Evidence needs an explicitly declared status from its type's allow-list:

| Node type | Accepted statuses |
| --- | --- |
| Artifact | recorded, captured, available, completed, verified |
| EnvironmentSnapshot | recorded, captured, completed, verified |
| Observation | recorded, observed, confirmed, completed, verified |
| ToolOutput | completed, succeeded |
| Verification / VerificationReceipt | completed, succeeded, passed, verified |
| AcceptanceCriterion | satisfied, passed, verified |

Missing, unknown, blocked and skipped statuses cannot open the claim gate.
`minimum_support_count` must be a positive integer and counts distinct evidence
node IDs, not parallel copies of a supports relation. Historical success paths
also require a receipt with an accepted completion status. Existing ledgers
remain readable, but unspecified receipt/evidence statuses no longer qualify
automatically; add an explicit evidence-backed status event when appropriate.

## 6. Historical reconstruction

The importer is read-only. Historical events are marked `reconstructed`; the page repeats that boundary when the selected node originates from reconstructed records.

Cross-case reuse is also derived. A current candidate may match history only through an explicit `reuse_key` / `reuse_keys` attribute, never label similarity. A historical path is called `verified_success_path` only when its Case has an explicit closed/completed state and that same historical Run has a non-derived `VerificationReceipt`; a receipt in another Run cannot qualify it. Reconstructed or synthetic matches remain `advisory_only_non_live_history` and never prove a current live Run.

## 7. Deliberately removed

Earlier iterations grew PlantUML/sequence outputs, loop/trace/reader/story/workbench models, a spatial catalog, a replay catalog, locale bundles and authored presentation overlays. They duplicated the canonical graph without adding facts and were removed. New analytical views must stay optional consumers of `graph.json`; they cannot become new facts.
