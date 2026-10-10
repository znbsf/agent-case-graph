from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from agent_case_graph.model import load_events
from agent_case_graph.projector import project_events
from agent_case_graph.trace_model import build_trace_model
from agent_case_graph.loop_projection import build_loop_projection
from agent_case_graph.reader import build_reader_model, render_reader_html


def fixture():
    nodes = []
    def node(key, kind, label=None, **attrs):
        nodes.append(dict(id=key, type=kind, label=label or key, attrs=attrs,
                          first_sequence=len(nodes)+1, status=attrs.get('status', 'recorded'),
                          provenance={'capture_modes':['reconstructed'], 'source_refs':['example:reader']}))
    node('case','Case',coverage={'returned_turn_metadata':4, 'turns_with_visible_items':2, 'turns_without_items':2})
    for suffix in ('a','b'):
        node('goal:'+suffix,'Goal')
        node('plan:'+suffix,'Plan')
        node('action:'+suffix,'Action')
        node('output:'+suffix,'ToolOutput',status='recorded')
        node('claim:'+suffix,'Claim',status='reported')
    node('artifact','Artifact',source_uri='https://example.com/report', sha256='a'*64)
    node('counter','Claim','Unsupported performance claim',status='refuted')
    edges = []
    def edge(kind, source, target):
        edges.append(dict(id=f'e{len(edges)}',type=kind,**{'from':source,'to':target}))
    for suffix in ('a','b'):
        edge('frames','goal:'+suffix,'plan:'+suffix)
        edge('invokes','plan:'+suffix,'action:'+suffix)
        edge('produces','action:'+suffix,'output:'+suffix)
        edge('supports','output:'+suffix,'claim:'+suffix)
        edge('contains','case','plan:'+suffix)
    edge('references','output:a','artifact')
    edge('refutes','output:a','counter')
    groups = [dict(id='stage:'+suffix, source_group_id='stage:'+suffix, label='Stage '+suffix,
                   attrs={'loop_scope':'execution','member_ids':[kind+':'+suffix for kind in ('plan','action','output','claim')], 'explicit':False})
              for suffix in ('a','b')]
    graph = dict(graph_id='graph:reader',root_id='case',nodes=nodes,edges=edges)
    trace = dict(nodes=nodes,edges=edges,overview={'nodes':groups},trace=[{'capture_mode':'reconstructed'}])
    return graph, trace


class ReaderTests(unittest.TestCase):
    def test_stages_have_question_action_result_and_provenance(self):
        graph, trace = fixture()
        model = build_reader_model(graph,trace)
        first = model['stages'][0]
        self.assertEqual(['goal:a'],first['goal_ids'])
        self.assertEqual(['action:a'],first['action_ids'])
        self.assertEqual(['output:a'],first['result_ids'])
        self.assertEqual(['claim:a'],first['conclusion_ids'])
        self.assertEqual(['example:reader'],first['source_refs'])
        self.assertFalse(first['explicit_iteration'])
        self.assertEqual(2,model['coverage']['turns_without_items'])

    def test_scope_keeps_counterevidence_without_importing_sibling_stage(self):
        graph, trace = fixture()
        first = build_reader_model(graph,trace)['stages'][0]
        self.assertIn('artifact',first['related_node_ids'])
        self.assertIn('counter',first['related_node_ids'])
        self.assertTrue(first['counterevidence_ids'])
        self.assertNotIn('output:b',first['related_node_ids'])
        self.assertNotIn('claim:b',first['related_node_ids'])

    def test_projection_does_not_mutate_inputs_or_upgrade_reported_claims(self):
        graph, trace = fixture()
        before = copy.deepcopy((graph,trace))
        model = build_reader_model(graph,trace)
        self.assertEqual(before,(graph,trace))
        self.assertFalse(model['principles']['stage_order_is_causality'])
        self.assertFalse(model['principles']['status_is_new_verification'])
        self.assertEqual('reported',next(node['status'] for node in model['nodes'] if node['id']=='claim:a'))

    def test_html_escapes_source_markup_and_does_not_reexpand_source_tokens(self):
        graph, trace = fixture()
        trace['nodes'][1]['label'] = '</script><img src=x onerror=alert(1)> __STYLE__ __SCRIPT__'
        document = render_reader_html(build_reader_model(graph,trace), title='<unsafe> __DATA__')
        self.assertNotIn('<img src=x',document)
        self.assertIn('\\u003c/script>',document)
        self.assertIn('__STYLE__ __SCRIPT__',document)
        self.assertIn('&lt;unsafe&gt; __DATA__',document)
        self.assertIn("default-src 'none'",document)
        self.assertNotIn('<script src=',document)

    def test_unknown_coverage_is_not_fabricated_as_zero(self):
        graph, trace = fixture()
        graph['nodes'][0]['attrs']['coverage'] = {'turns_without_items':True, 'returned_turn_metadata':-1, 'turns_with_visible_items':1.5}
        self.assertEqual({},build_reader_model(graph,trace)['coverage'])

    def test_previous_output_informs_but_is_not_the_next_stages_result(self):
        graph, trace = fixture()
        trace['overview']['nodes'][1]['attrs']['member_ids'].append('output:a')
        trace['edges'].append({'id':'informs-next','type':'informs','from':'output:a','to':'plan:b'})
        second = build_reader_model(graph,trace)['stages'][1]
        self.assertIn('output:a',second['related_node_ids'])
        self.assertEqual(['output:b'],second['result_ids'])
        self.assertEqual(['claim:b'],second['conclusion_ids'])
        self.assertEqual([],second['counterevidence_ids'])

    def test_empty_graph_has_no_fabricated_stage(self):
        graph, trace = fixture()
        trace['overview']['nodes']=[]
        self.assertEqual([],build_reader_model(graph,trace)['stages'])

    def test_shared_refuted_hypothesis_is_counterevidence_not_an_owned_conclusion(self):
        graph, trace = fixture()
        trace['overview']['nodes'][0]['attrs']['member_ids'].append('counter')
        trace['edges'].append({'id':'other-refutation','type':'refutes','from':'output:b','to':'counter'})
        first = build_reader_model(graph,trace)['stages'][0]
        self.assertNotIn('counter',first['conclusion_ids'])
        self.assertNotIn('other-refutation',first['counterevidence_ids'])
        self.assertNotIn('other-refutation',first['relation_ids'])
        self.assertNotIn('output:b',first['related_node_ids'])
        self.assertEqual(1,len(first['counterevidence_ids']))

    def test_shared_plan_iterations_have_unique_navigation_and_isolated_results(self):
        graph, trace = fixture()
        trace['overview']['nodes'][1]['attrs']['member_ids'][0] = 'plan:a'
        trace['edges'].append({'id':'shared-plan','type':'invokes','from':'plan:a','to':'action:b'})
        stages = build_reader_model(graph,trace)['stages']
        self.assertEqual(2,len({stage['id'] for stage in stages}))
        self.assertEqual(['action:a'],stages[0]['action_ids'])
        self.assertEqual(['action:b'],stages[1]['action_ids'])
        self.assertEqual(['output:a'],stages[0]['result_ids'])
        self.assertEqual(['output:b'],stages[1]['result_ids'])

    def test_sources_and_boundaries_are_visible_without_parsing_label_sentiment(self):
        graph, trace = fixture()
        trace['nodes'][2]['attrs'].update(source_kind='workspace_artifact_supplement',boundary='Not a physical device result.')
        stage = build_reader_model(graph,trace)['stages'][0]
        self.assertEqual(['workspace_artifact_supplement'],stage['source_kinds'])
        self.assertEqual(['Not a physical device result.'],stage['boundaries'])
        self.assertNotIn('passed',stage)

    def test_quickstart_without_authored_plans_remains_readable(self):
        path = Path(__file__).resolve().parents[1]/'examples/quickstart/events.jsonl'
        events = load_events(path)
        graph = project_events(events)
        trace = build_trace_model(graph,events)
        trace['overview'] = build_loop_projection(graph,trace)
        model = build_reader_model(graph,trace)
        self.assertTrue(model['stages'])
        self.assertEqual(['synthetic'],model['capture_modes'])
        self.assertEqual(len(events),model['event_count'])


if __name__ == '__main__':
    unittest.main()
