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

The Workflow tab is a deliberate projection: it includes workflow nodes plus
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

Only authored canonical edges are rendered.

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

`graph.html` is a self-contained linked view:

- left: source Trace Records;
- center: Loop Overview / Workflow / Evidence / Trace;
- right: selected node details and relations;
- selection highlights direct audit neighbors;
- locale bundles alter display labels only.

The HTML contains no CDN dependency and never executes an Action.

## 6. Runtime remains separate

Only explicit `runtime_managed=true` Step, Action and Verification nodes inside a Run enter the control plane. `next-actions` uses `precedes / blocked_by / approved_by`; `step-status` appends a checkpoint after validating the transition.

An executable node's minimal context packet follows incoming context lineage for
at most three hops, so `Action <- Plan <- Goal/ReasoningSummary` is available
without loading the whole graph.

The visual trace can explain runtime state but cannot declare a node Ready, grant approval or invoke tools.

## 7. Historical reconstruction

The importer is read-only. Historical events are marked `reconstructed`; the page repeats that boundary when the selected node originates from reconstructed records. Visual replay is always `visual_only=true` and `reexecutes_actions=false`.

## 8. Deliberately removed from the reset

- orthogonal planes and 3D projection;
- five parallel workspace modes;
- duplicated node cards across Overview/Plan/Run/Review/Evidence;
- animated execution lines without explicit telemetry;
- Mermaid output;
- renderer-owned spatial catalog.

Future analytical views such as embeddings or cross-run process mining must be optional consumers of the canonical graph. They cannot change the core DAG or become new facts.
