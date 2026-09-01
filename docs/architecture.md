# Agent Case Graph architecture

## 1. Product boundary

ACG is an evidence-first trace protocol, not a drawing engine. The durable layer records what happened and what relations were explicitly declared. Rendering remains replaceable.

```text
Event Ledger -> Canonical Graph -> paper-trace-0.1 -> PlantUML / HTML
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

The three levels follow the review hierarchy used by LEDGER: raw records remain available, related work is inspectable as evidence, and the default graph is compressed into workflow phases.

The Workflow tab is a deliberate projection: it includes workflow nodes plus
evidence nodes that participate in a forward layout edge. Other evidence is
not deleted; it remains in the Evidence tab, source Trace, and node relations.
Containment is drawn only to branch roots rather than repeated beside every
flow edge. Large ranks wrap after three cards without changing their canonical
rank.

## 4. Relation policy

Only authored canonical edges are rendered.

- solid: forward workflow or dependency relations such as `precedes`, `implemented_by`, `targets`;
- dotted: evidence and provenance such as `supports`, `checks`, `uses`, `produces`, `derived_from`;
- quiet: containment relations such as `has_run`, `contains`.

Only the forward workflow/dependency set constrains DAG rank. Evidence and
provenance relations remain authored facts, but they are reviewed in the HTML
Evidence tab and node details rather than fed back into the workflow topology.
This prevents a valid claim-to-evidence audit loop from turning the main graph
into a false one-node-per-rank chain.

The renderer never creates a missing support path from node types. A final Claim without explicit support remains visibly incomplete and is handled by lint.

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
- center: Workflow / Evidence / Trace;
- right: selected node details and relations;
- selection highlights direct audit neighbors;
- locale bundles alter display labels only.

The HTML contains no CDN dependency and never executes an Action.

## 6. Runtime remains separate

Only explicit `runtime_managed=true` Step, Action and Verification nodes inside a Run enter the control plane. `next-actions` uses `precedes / blocked_by / approved_by`; `step-status` appends a checkpoint after validating the transition.

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
