# Agent Case Graph architecture

## 1. Product boundary

ACG is an evidence-first trace protocol, not a drawing engine. The durable layer records what happened and what relations were explicitly declared. Rendering remains replaceable.

```text
Event Ledger -> Canonical Graph -> paper-trace-0.1 -> loop/sequence projections -> PlantUML / HTML
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

The canonical graph retains stable IDs, typed nodes and typed edges. Runtime gates, lint and replay consume this graph; no renderer is allowed to infer causality from coordinates or timestamps.

The sequence projection groups semantic nodes by projected `ExecutionIteration`
and linearizes typed temporal constraints; the first source Ledger sequence is
only a stable tie-breaker. It is deliberately a readability view: vertical
adjacency is not causality. Typed relations such as `frames`, `informs`,
`supersedes`, `supports`, `invokes`, and `produces` remain canonical graph edges
and are exposed by the workflow/evidence views.

## 3. Review projection

`trace_model.build_trace_model()` is the only adapter between the canonical graph and both renderers.

```text
Workflow Node
  phase = context | plan | inspect | execute | validate | claim
  id + label + type + status

Evidence Node
  Observation | Artifact | Verification | Claim | AcceptanceCriterion | Uncertainty

Trace Record
  sequence + event kind + actor + capture mode + source refs
```

The review hierarchy keeps raw records available, makes evidence inspectable, and adds a derived nested-loop overview above workflow phases.

```text
DialogueRound (outer conversation loop)
  └─ ExecutionIteration (inner agent execution loop)
       └─ canonical Goal / Plan / ToolCall / ToolOutput / Evaluation nodes
```

`DialogueRound`, `ExecutionIteration`, `UserFeedback`, `AgentResponse`, and
`Evaluation` may be recorded as canonical nodes. Their parent scope is declared
only by `contains`; their causal order still requires authored edges.
`Aggregate` is never a canonical node type. It exists only inside the derived
`loop-model.json`/HTML model.

The loop projection is non-mutating. It preserves member node IDs, internal and
cycle edge IDs, cross-group raw endpoints and provenance. Nodes or edges that
cannot be assigned are reported explicitly as unmapped. Missing dialogue input
evidence produces a display fallback, not a claimed user turn. Acceptance and
first-attempt success remain unknown without an explicit accepted signal.

The Sequence projection linearizes one execution aggregate from explicit typed
temporal constraints. Forward relations such as `precedes`, `invokes`, and
`produces` retain direction; review-style relations such as `checks` and
`supersedes` are interpreted in their temporal direction. Ready peers use the
first source Ledger sequence only as a deterministic tie-breaker. The original
source sequence remains visible, and adjacency in the resulting total order is
not promoted to a causal claim.

The following phase-layout details describe the static/legacy technical
renderer (`workbench-legacy.html`), not the new stage-first workbench.
Its Workflow tab is a deliberate projection: it includes workflow nodes plus
evidence nodes that participate in a forward layout edge. Other evidence is
not deleted; it remains in the Evidence tab, source Trace, and node relations.
Containment remains available in node details, but it does not constrain or
appear in the main workflow layout. Scope membership is not an execution
dependency. Large ranks wrap after three cards without changing their canonical
rank.

Within one rank, horizontal order is display-only. The HTML renderer performs
six top-down/bottom-up neighbor-median sweeps, then uses the node's first source
sequence and stable ID as tie-breakers. This reduces crossings without turning
source order into a causal edge.

The HTML router assigns separate source and target ports for fan-out and
fan-in. Adjacent forward edges use bottom-to-top curves; reverse relations use
top-to-bottom curves; same-rank relations use row-external lanes. When one
canonical rank wraps across visual rows, or an edge spans more than one visual
row, the route uses a side channel so it does not pass through intermediate
cards. These route classes are display metadata only and never rewrite edge
direction, type, or canonical rank.

The Evidence tab deliberately expands one authored evidence hop from nodes
marked as evidence. That neighborhood is computed from a fixed seed set, so it
is deterministic without pulling an entire connected component into a single
review view.

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

## 5. Two renderers, one model

### PlantUML

`trace.puml` is the static contract review:

- top-down DAG;
- branch and merge using only forward layout edges;
- phase color, type, status and relation labels;
- deterministic text artifact suitable for diffs.

It does not implement filters, evidence back-links, details, live refresh or
artifact preview.

### HTML

`graph.html` is the default key-path graph. `story_graph.build_story_model()`
consumes the reader scopes without changing canonical nodes or verdicts.
Without annotations, it displays every stage and its recorded conclusions.
An explicit `project --presentation` JSON can assign main/branch cards and up to
three concise outcome annotations per card. It must match the exact source
ledger SHA256, cover all stages exactly once, reference existing source nodes,
and attach branches only to main cards. Outcome references must be in the
card's scope. Validation checks structure and staleness, not semantic truth.
Tones such as `gain`, `negative`, or `paused` are editorial, not verification.

The graph uses measured HTML card geometry with SVG layout connectors; no
fixed-width text truncation or fit-to-screen font shrinking is needed. Dashed
connectors mean review order or topic grouping, never causality. Selecting a
card expands only its scope below the row and preserves its screen position.
The local action/output/conclusion arrows require matching original typed
relations. Shared refuted hypotheses remain counterevidence, not owned claims
that could import sibling-stage results. Branches reflow below their parent on
narrow screens. Keyboard activation, Escape, deep links and browser Back work
without external dependencies. `story-model.json` records the display model.

`reader.html` is the auxiliary, self-contained reading view. `reader.build_reader_model()`
projects loop members into source-linked question / action / result / conclusion
spans. Scope evidence uses one explicit relation hop, ignoring containment.
For Plan-based spans, results must be produced by that Plan's invoked actions;
an informing output from an earlier span remains context, not a new result.
No label sentiment parsing, new verification verdicts, or inferred causal edges
are introduced. Unknown questions/coverage remain unknown. Capture modes and
recorded missing-content counts are prominent. Raw fields are collapsed.

The reader has its own `review-model.json` contract. Its HTML/CSS/JavaScript live
under packaged `web/` resources, are inlined into the generated page, and use no
external runtime dependencies. Source text is escaped in the JSON script block
and rendered with `textContent`. Only explicit http/https/codex/file source
references become links; other schemes remain inert, and nothing is auto-loaded.

`workbench.html` uses a separate `evidence-workbench-0.1` model:

- left: collapsible stage navigation;
- center: Stages / Stage relations / Evidence / Sequence / Source records;
- right: on-demand node, canonical-edge, aggregate-witness or research details;
- selection can filter to one explicit relation hop, not just dim the full graph;
- locale bundles alter display labels only.

Each canonical node belongs to exactly one display group. Shared ownership and
unscoped nodes have explicit separate groups. Internal edge IDs plus cross-group
`source_edge_ids` cover every original edge exactly once. Source endpoints,
types, provenance and statuses are unchanged. Stage-local context follows the
reader scope, keeping shared refuted claims from importing sibling results.

Local graphs use measured HTML cards and a simplified stable layered layout;
the obstacle-aware orthogonal router does not reverse or delete source edges.
All-stage role columns and stage order are display-only. Sequence relations
remain separately styled as order; evidence, containment and other recorded
relations retain their types. Overview filters hide detail without deleting it.
Zoom scales a scrollable world rather than resetting the scroll position;
source events are paginated rather than duplicated next to the whole graph.

This is not a reproduction of dot, nor a validated usability experiment.
See [research basis and validation boundaries](workbench-research-basis.md).
The original technical renderer remains available as `workbench-legacy.html`.

The HTML contains no CDN dependency and never executes an Action.

## 6. Runtime remains separate

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

## 7. Historical reconstruction

The importer is read-only. Historical events are marked `reconstructed`; the page repeats that boundary when the selected node originates from reconstructed records. Visual replay is always `visual_only=true` and `reexecutes_actions=false`.

Cross-case reuse is also derived. A current candidate may match history only through an explicit `reuse_key` / `reuse_keys` attribute, never label similarity. A historical path is called `verified_success_path` only when its Case has an explicit closed/completed state and that same historical Run has a non-derived `VerificationReceipt`; a receipt in another Run cannot qualify it. Reconstructed or synthetic matches remain `advisory_only_non_live_history` and never prove a current live Run.

## 8. Deliberately removed from the reset

- orthogonal planes and 3D projection;
- five parallel workspace modes;
- duplicated node cards across Overview/Plan/Run/Review/Evidence;
- animated execution lines without explicit telemetry;
- Mermaid output;
- renderer-owned spatial catalog.

Future analytical views such as embeddings or cross-run process mining must be optional consumers of the canonical graph. They cannot change the core DAG or become new facts.
