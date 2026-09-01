# Paper and open-source visualization notes

## Decision

The reset uses a top-down layered DAG as the primary reading surface. PlantUML is the static baseline; self-contained HTML adds linked inspection. Three-dimensional geometry is not part of the core review grammar.

## Primary research sources

### Graph of Trace

[Graph of Trace: Visualizing Execution Traces of Scientific Agents](https://aclanthology.org/2026.acl-demo.29/) records atomic subtasks and declared dependencies in an append-only graph. Figure 2 uses three coordinated panels:

1. conversational and stepwise agent activity;
2. layered top-down DAG;
3. selected node metadata, parents and intermediate outputs.

Figure 3 shows the important structural vocabulary: linear stages, parallel sibling branches, explicit aggregation and ellipsis for omitted regions.

### LEDGER

[LEDGER: Claim-to-Evidence Trace Graphs for Auditing LLM Agents](https://arxiv.org/abs/2608.18398) separates three review layers:

```text
Trace Records -> Evidence Nodes -> Workflow Nodes
```

Its workflow categories are `context / plan / inspect / execute / validate / claim`. Artifacts remain inspectable evidence anchors, and typed edges connect claims to actions, files and checks. The graph is an index into evidence, not a replacement for evidence.

### AgentDiagnose

[AgentDiagnose](https://aclanthology.org/2025.emnlp-demos.15/) uses linked views for state transitions, action embeddings, word clouds and trajectory details. This supports keeping diagnostic analytics separate from the core DAG: a statistical view can locate a suspicious region, but must resolve back to a concrete trajectory step.

## Minimal visual grammar

1. One node is one reviewable work unit.
2. Default to Workflow phases; drill down to Evidence and Trace.
3. Use a top-down DAG with explicit branch and merge.
4. Keep node text short; move tool input/output and source records to details.
5. Distinguish actions, artifacts, validations and claims.
6. Render only explicit typed relations.
7. Preserve reverse audit from Claim to evidence.
8. Collapse or omit large regions instead of adding more colors and crossing lines.
9. Keep analysis views optional.
10. Never claim native telemetry for reconstructed records.

## PlantUML versus HTML

| Capability | PlantUML | HTML |
| --- | --- | --- |
| Static layered DAG | Primary | Primary |
| Branch, merge, relation label | Yes | Yes |
| Deterministic diff | Strong | Generated artifact only |
| Node selection and linked details | No | Yes |
| Workflow / Evidence / Trace switch | No | Yes |
| Artifact/source inspection | Link only | Details and future preview adapters |
| Collapse, filter, live refresh | Limited | Extension point |
| Append-only capture and runtime gates | Backend concern | Backend concern |

Both renderers consume `trace-model.json`; neither may reinterpret the canonical graph.

## Useful implementations

- [Graph of Trace official repository](https://github.com/NeuroAIHub/Graph-of-Trace)
- [AgentDiagnose official repository](https://github.com/oootttyyy/AgentDiagnose)
- [PlantUML](https://github.com/plantuml/plantuml)
- [W3C PROV-O](https://www.w3.org/TR/prov-o/)
