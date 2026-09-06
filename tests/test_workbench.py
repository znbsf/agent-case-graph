from __future__ import annotations

from collections import Counter
import copy
import unittest

from agent_case_graph.reader import build_reader_model
from agent_case_graph.workbench import build_workbench_model, render_workbench_html
from tests.test_reader import fixture


class WorkbenchTests(unittest.TestCase):
    def model(self):
        graph, trace = fixture()
        return build_workbench_model(build_reader_model(graph, trace), trace)

    def test_every_canonical_node_appears_in_exactly_one_group(self):
        model = self.model()
        members = [key for group in model['groups'] for key in group['member_ids']]
        self.assertEqual(Counter(n['id'] for n in model['nodes']), Counter(members))
        self.assertTrue(all(model['node_owner'][key] == group['id']
                            for group in model['groups'] for key in group['member_ids']))

    def test_every_edge_is_internal_or_has_exact_summary_witness_once(self):
        model = self.model()
        witnesses = [key for edge in model['group_edges'] for key in edge['source_edge_ids']]
        internal = [key for group in model['groups'] for key in group['internal_edge_ids']]
        self.assertEqual(Counter(e['id'] for e in model['edges']),Counter(witnesses+internal))
        sources = {e['id']:e for e in model['edges']}
        for edge in model['group_edges']:
            for key in edge['source_edge_ids']:
                original = sources[key]
                self.assertEqual(original['type'],edge['type'])
                self.assertEqual(model['node_owner'][original['from']],edge['from'])
                self.assertEqual(model['node_owner'][original['to']],edge['to'])

    def test_shared_plan_is_not_arbitrarily_attributed_to_one_stage(self):
        graph, trace = fixture()
        trace['overview']['nodes'][1]['attrs']['member_ids'].append('plan:a')
        model = build_workbench_model(build_reader_model(graph,trace),trace)
        group = next(g for g in model['groups'] if g['id']==model['node_owner']['plan:a'])
        self.assertEqual('shared',group['kind'])
        self.assertIn('plan:a',group['member_ids'])

    def test_shared_refutation_never_imports_another_stages_results(self):
        graph, trace = fixture()
        trace['overview']['nodes'][0]['attrs']['member_ids'].append('counter')
        trace['edges'].append({'id':'b-refutes','from':'output:b','to':'counter','type':'refutes'})
        model = build_workbench_model(build_reader_model(graph,trace),trace)
        scope = next(s for s in model['scopes'] if s['id']=='plan:a')
        self.assertNotIn('output:b',scope['related_node_ids'])
        self.assertNotIn('counter',scope['conclusion_ids'])
        self.assertIn('counter',scope['related_node_ids'])

    def test_order_edges_do_not_become_causal_and_adjacency_creates_no_edge(self):
        graph, trace = fixture()
        trace['edges'].append({'id':'order','from':'plan:a','to':'plan:b','type':'precedes'})
        model = build_workbench_model(build_reader_model(graph,trace),trace)
        order = next(e for e in model['group_edges'] if 'order' in e['source_edge_ids'])
        self.assertEqual('order',order['relation_class'])
        self.assertEqual(['order'],order['source_edge_ids'])
        self.assertFalse(model['principles']['recorded_relation_is_verified_cause'])
        self.assertFalse(model['principles']['papers_validate_this_ui'])

    def test_projection_and_render_leave_source_and_status_unchanged(self):
        graph, trace = fixture()
        before = copy.deepcopy((graph,trace))
        model = build_workbench_model(build_reader_model(graph,trace),trace)
        render_workbench_html(model,title='Test')
        self.assertEqual(before,(graph,trace))
        self.assertEqual('reported',next(n['status'] for n in model['nodes'] if n['id']=='claim:a'))

    def test_no_stage_still_keeps_all_nodes_and_edges(self):
        graph, trace = fixture()
        trace['overview']['nodes']=[]
        model = build_workbench_model(build_reader_model(graph,trace),trace)
        self.assertEqual(1,len(model['groups']))
        self.assertEqual('unscoped',model['groups'][0]['kind'])
        self.assertEqual(len(trace['edges']),len(model['groups'][0]['internal_edge_ids']))

    def test_source_tokens_and_markup_stay_inert(self):
        graph, trace = fixture()
        trace['nodes'][0]['label']='</script><img src=x onerror=alert(1)> __LAYOUT__'
        doc = render_workbench_html(build_workbench_model(build_reader_model(graph,trace),trace),title='<title> __DATA__')
        self.assertNotIn('<img src=x',doc)
        self.assertIn('\\u003c/script>',doc)
        self.assertIn('__LAYOUT__',doc)
        self.assertIn('&lt;title&gt; __DATA__',doc)
        self.assertIn("default-src 'none'",doc)

    def test_display_ids_cannot_shadow_canonical_node_ids(self):
        graph, trace = fixture()
        trace['nodes'][0]['id']='display:scope:plan:a'
        graph['root_id']='display:scope:plan:a'
        for edge in trace['edges']:
            if edge['from']=='case':edge['from']='display:scope:plan:a'
        model = build_workbench_model(build_reader_model(graph,trace),trace)
        self.assertFalse({n['id'] for n in model['nodes']} & {g['id'] for g in model['groups']})

    def test_papers_include_publication_and_evidence_limits(self):
        model = self.model()
        self.assertTrue(all(p['sections'] and p['limit'] and p['url'].startswith('https:') for p in model['papers']))
        self.assertIn('preprint',next(p['publication'] for p in model['papers'] if p['id']=='ledger'))

    def test_display_group_ids_cannot_shadow_canonical_edges(self):
        graph, trace = fixture()
        trace['edges'][0]['id']='display:scope:plan:a'
        model = build_workbench_model(build_reader_model(graph,trace),trace)
        display = {g['id'] for g in model['groups']} | {e['id'] for e in model['group_edges']}
        self.assertFalse(display & {e['id'] for e in model['edges']})


if __name__=='__main__':unittest.main()
