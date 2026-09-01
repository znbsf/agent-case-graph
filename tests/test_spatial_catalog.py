import copy
import unittest

from agent_case_graph.spatial import (
    SPATIAL_PROTOCOL_VERSION,
    build_spatial_catalog,
)


def _node(node_id, node_type, sequence, *, runtime_managed=False):
    attrs = {}
    if runtime_managed:
        attrs["runtime_managed"] = True
    return {
        "id": node_id,
        "type": node_type,
        "label": node_id,
        "attrs": attrs,
        "first_sequence": sequence,
    }


def _edge(edge_id, edge_type, source, target, sequence, **attrs):
    return {
        "id": edge_id,
        "type": edge_type,
        "from": source,
        "to": target,
        "attrs": attrs,
        "first_sequence": sequence,
    }


def _graph(*, with_runtime=True):
    nodes = [
        _node("case:1", "Case", 1),
        _node("decision:1", "Decision", 2),
        _node("run:1", "Run", 3),
        _node("step:1", "Step", 4, runtime_managed=with_runtime),
        _node("action:1", "Action", 5, runtime_managed=with_runtime),
        _node("approval:1", "Approval", 6),
        _node("observation:1", "Observation", 7),
        _node("verification:1", "Verification", 8, runtime_managed=with_runtime),
    ]
    edges = [
        _edge("e-target", "targets", "case:1", "decision:1", 9),
        _edge("e-contains-step", "contains", "run:1", "step:1", 10),
        _edge("e-contains-action", "contains", "run:1", "action:1", 11),
        _edge("e-contains-verification", "contains", "run:1", "verification:1", 12),
        _edge("e-precedes", "precedes", "step:1", "action:1", 13),
        _edge("e-produces", "produces", "action:1", "observation:1", 14),
        _edge("e-supports", "supports", "observation:1", "decision:1", 15),
        _edge("e-approved", "approved_by", "action:1", "approval:1", 16),
    ]
    graph = {
        "schema_version": "0.1.0",
        "graph_id": "graph:1",
        "graph_type": "case",
        "root_id": "case:1",
        "generated_at": "2026-08-31T10:00:16+08:00",
        "nodes": nodes,
        "edges": edges,
    }
    if with_runtime:
        graph["runtime"] = {
            "protocol_version": "runtime-0.1",
            "runs": [
                {
                    "run_id": "run:1",
                    "run_label": "selected run",
                    "status": "configured",
                    "case_state": "execute",
                    "counts": {"ready": 0, "running": 1, "completed": 2},
                    "ready": [],
                    "running": [
                        {
                            "id": "action:1",
                            "type": "Action",
                            "label": "action:1",
                            "status": "running",
                        }
                    ],
                    "blocked": [],
                    "completed": [
                        {
                            "id": "step:1",
                            "type": "Step",
                            "label": "step:1",
                            "status": "completed",
                        },
                        {
                            "id": "verification:1",
                            "type": "Verification",
                            "label": "verification:1",
                            "status": "completed",
                        },
                    ],
                    "failed": [],
                }
            ],
        }
    return graph


class SpatialCatalogTests(unittest.TestCase):
    def test_catalog_has_one_primary_surface_and_relation_interfaces(self):
        catalog = build_spatial_catalog(_graph())

        self.assertEqual(SPATIAL_PROTOCOL_VERSION, catalog["protocol_version"])
        self.assertEqual(
            {"case:1", "observation:1"},
            set(catalog["layers"]["state"]["membership"]),
        )
        self.assertEqual(
            {"run:1", "step:1", "decision:1", "approval:1", "verification:1"},
            set(catalog["layers"]["control"]["membership"]),
        )
        self.assertEqual(
            {"action:1"},
            set(catalog["layers"]["action"]["membership"]),
        )
        self.assertEqual(
            [], catalog["interfaces"]["state-control"]["membership"]
        )
        self.assertEqual(
            {"e-target", "e-supports"},
            set(catalog["interfaces"]["state-control"]["relation_ids"]),
        )
        self.assertEqual(
            {"e-contains-action", "e-precedes", "e-approved"},
            set(catalog["interfaces"]["control-action"]["relation_ids"]),
        )
        self.assertEqual(
            {"e-produces"},
            set(catalog["interfaces"]["action-state"]["relation_ids"]),
        )
        self.assertTrue(all(len(item["membership"]) == 1 for item in catalog["nodes"]))
        self.assertTrue(all(item["primary_layer"] == item["membership"][0] for item in catalog["nodes"]))

    def test_selected_runtime_instances_are_explicit_and_relations_are_annotated(self):
        catalog = build_spatial_catalog(_graph())

        selected = catalog["selected_runtime"]
        self.assertEqual("run:1", selected["run_id"])
        self.assertEqual(
            ["step:1", "action:1", "verification:1"], selected["node_ids"]
        )
        self.assertEqual(
            ["run:1::step:1", "run:1::action:1", "run:1::verification:1"],
            selected["instance_ids"],
        )
        self.assertEqual("populated", catalog["layers"]["state"]["status"])
        self.assertTrue(all(item["membership"] == ["runtime-overlay"] for item in selected["instances"]))
        self.assertEqual(
            ["step:1", "action:1", "verification:1"], catalog["runtime_overlay"]["node_ids"]
        )

        by_id = {item["id"]: item for item in catalog["relations"]}
        self.assertEqual("control-action", by_id["e-precedes"]["flow_kind"])
        self.assertTrue(by_id["e-precedes"]["actual"])
        self.assertFalse(by_id["e-precedes"]["animated"])
        self.assertEqual("action-state", by_id["e-produces"]["flow_kind"])
        self.assertFalse(by_id["e-produces"]["animated"])
        self.assertEqual("state-control", by_id["e-supports"]["flow_kind"])
        self.assertFalse(by_id["e-supports"]["animated"])
        self.assertIn("action-state", by_id["e-produces"]["interfaces"])
        self.assertEqual("run:1::action:1", by_id["e-produces"]["from_instance_id"])
        self.assertTrue(by_id["e-produces"]["runtime_touched"])
        self.assertFalse(by_id["e-produces"]["animated"])

    def test_no_runtime_makes_overlay_explicitly_empty_without_changing_surfaces(self):
        graph = _graph(with_runtime=False)
        catalog = build_spatial_catalog(graph)

        runtime_overlay = catalog["runtime_overlay"]
        self.assertEqual("empty", runtime_overlay["status"])
        self.assertEqual([], runtime_overlay["membership"])
        self.assertEqual([], runtime_overlay["node_ids"])
        self.assertEqual([], runtime_overlay["instance_ids"])
        self.assertEqual([], runtime_overlay["nodes"])
        self.assertIsNone(runtime_overlay["selected_runtime"])
        self.assertIsNone(catalog["selected_runtime"])
        self.assertEqual({"action:1"}, set(catalog["layers"]["action"]["node_ids"]))
        self.assertTrue(all(len(item["membership"]) == 1 for item in catalog["nodes"]))

    def test_catalog_is_independent_of_input_array_order_and_has_no_layout_facts(self):
        graph = _graph()
        shuffled = copy.deepcopy(graph)
        shuffled["nodes"] = list(reversed(shuffled["nodes"]))
        shuffled["edges"] = list(reversed(shuffled["edges"]))
        runtime_run = shuffled["runtime"]["runs"][0]
        runtime_run["completed"] = list(reversed(runtime_run["completed"]))
        runtime_run["running"] = list(reversed(runtime_run["running"]))

        self.assertEqual(build_spatial_catalog(graph), build_spatial_catalog(shuffled))
        catalog = build_spatial_catalog(graph)
        self.assertFalse(any("x" in node or "y" in node for node in catalog["nodes"]))
        self.assertNotIn("layout", catalog)


if __name__ == "__main__":
    unittest.main()
