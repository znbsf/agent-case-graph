from copy import deepcopy
import json
import re
import unittest
from xml.etree import ElementTree as ET

from agent_case_graph.renderer import render_html


def example():
    nodes = [{"id": name, "type": kind, "label": name, "attrs": {},
              "first_sequence": i, "last_sequence": i, "event_ids": [],
              "provenance": {"capture_modes": ["synthetic"], "source_refs": []}}
             for i, (name, kind) in enumerate([
                 ("case", "Case"), ("run", "Run"), ("plan", "Plan"),
                 ("check", "Step"), ("deliver", "Step")], 1)]
    edges = [{"id": name, "type": kind, "from": source, "to": target, "attrs": attrs}
             for name, kind, source, target, attrs in [
                 ("run", "has_run", "case", "run", {}),
                 ("scope", "contains", "run", "plan", {}),
                 ("work", "invokes", "plan", "check", {}),
                 ("back", "informs", "check", "plan", {"条件": "需要调整或补证据"}),
                 ("done", "informs", "check", "deliver", {"condition": "验收满足"}),
             ]]
    return {"nodes": nodes, "edges": edges,
            "stats": {"event_count": 11, "node_count": len(nodes), "edge_count": len(edges), "capture_modes": {"synthetic": 11}}}


def canvas(page):
    return ET.fromstring(page.split('<div id="canvas">', 1)[1].split('</div>', 1)[0])


class RendererTests(unittest.TestCase):
    def test_collapsed_view_preserves_complete_graph_and_expansion(self):
        graph = example()
        before = deepcopy(graph)
        page = render_html(graph, title="Example")
        visible = {n.attrib["data-node"] for n in canvas(page).iter() if "data-node" in n.attrib}
        self.assertEqual({"plan", "check", "deliver"}, visible)
        full = ET.fromstring(page.split('<template id="expanded-graph">', 1)[1].split('</template>', 1)[0])
        self.assertEqual({n["id"] for n in graph["nodes"]}, {n.attrib["data-node"] for n in full.iter() if "data-node" in n.attrib})
        embedded = json.loads(re.search(r'const GRAPH = (.*);', page).group(1))
        self.assertEqual(graph["edges"], embedded["edges"])
        self.assertEqual(before, graph)

    def test_feedback_lane_is_outside_nodes_and_conditions_are_visible(self):
        svg = canvas(render_html(example(), title="Example"))
        nodes = {n.attrib["data-node"]: n for n in svg.iter() if "data-node" in n.attrib}
        edges = {n.attrib["data-edge"]: n for n in svg.iter() if "data-edge" in n.attrib}
        labels = {n.attrib["data-label-for"]: n.text for n in svg.iter() if "data-label-for" in n.attrib}
        path = re.fullmatch(r'M([\d.]+),([\d.]+) H([\d.]+) V([\d.]+) H([\d.]+)', edges["back"].attrib["d"])
        self.assertIsNotNone(path)
        start_x, start_y, lane, end_y, end_x = map(float, path.groups())
        self.assertLess(lane, min(float(n.attrib["transform"].split('(')[1].split(',')[0]) for n in nodes.values()))
        self.assertGreater(start_y, end_y)
        self.assertEqual(start_x, end_x)
        self.assertEqual("需要调整或补证据", labels["back"])
        self.assertEqual("验收满足", labels["done"])

    def test_condition_text_is_escaped(self):
        graph = example()
        text = '</text><script>alert("x")</script>'
        graph["edges"][-1]["attrs"]["condition"] = text
        page = render_html(graph, title="Escape")
        self.assertNotIn('<script>alert(', page)
        labels = {n.attrib["data-label-for"]: n.text for n in canvas(page).iter() if "data-label-for" in n.attrib}
        self.assertEqual(text, labels["done"])

    def test_container_only_graph_is_not_hidden(self):
        graph = example()
        graph["nodes"] = graph["nodes"][:2]
        graph["edges"] = graph["edges"][:1]
        page = render_html(graph, title="Containers")
        self.assertEqual(2, sum("data-node" in n.attrib for n in canvas(page).iter()))
        self.assertNotIn('<button id="protocol-toggle"', page)


if __name__ == "__main__":
    unittest.main()
