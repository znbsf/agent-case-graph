from __future__ import annotations

import copy
import unittest

from agent_case_graph.model import ACGError
from agent_case_graph.reader import build_reader_model
from agent_case_graph.story_graph import build_story_model, render_story_html
from test_reader import fixture


def story_fixture():
    graph, trace = fixture()
    graph['source_ledger'] = {'name':'events.jsonl','sha256':'a'*64}
    reader = build_reader_model(graph,trace)
    presentation = {'version':'case-story-0.1','source_sha256':'a'*64,'title':'Synthetic key path',
                    'cards':[{'id':'main','stage_ids':['plan:a'],'title':'First stage',
                              'results':[{'tone':'open','text':'Unresolved in source','source_ids':['claim:a']}]},
                             {'id':'branch','parent_id':'main','stage_ids':['plan:b'],'title':'A branch'}]}
    return reader, presentation


class StoryGraphTests(unittest.TestCase):
    def test_fallback_keeps_every_stage_without_guessing_outcomes(self):
        reader, _ = story_fixture()
        model = build_story_model(reader)
        self.assertFalse(model['authored'])
        self.assertEqual(2,len(model['cards']))
        self.assertTrue(all(not c['results'] and c['parent_id'] is None for c in model['cards']))

    def test_authored_layout_is_source_bound_and_non_mutating(self):
        reader, presentation = story_fixture()
        original = copy.deepcopy((reader,presentation))
        model = build_story_model(reader,presentation)
        self.assertTrue(model['authored'])
        self.assertFalse(model['principles']['layout_is_causality'])
        self.assertFalse(model['principles']['tones_are_verdicts'])
        self.assertEqual(original,(reader,presentation))
        self.assertEqual('reported',next(n['status'] for n in model['reader']['nodes'] if n['id']=='claim:a'))

    def test_stale_or_unhashed_source_is_rejected(self):
        reader, presentation = story_fixture()
        presentation['source_sha256']='b'*64
        with self.assertRaisesRegex(ACGError,'SHA256 mismatch'):build_story_model(reader,presentation)
        reader['source_ledger']=None
        with self.assertRaises(ACGError):build_story_model(reader,presentation)

    def test_stages_cannot_be_silently_dropped_or_duplicated(self):
        for change in ('missing','duplicate','unknown'):
            with self.subTest(change=change):
                reader, presentation = story_fixture()
                if change=='missing':presentation['cards'].pop()
                elif change=='duplicate':presentation['cards'][1]['stage_ids']=['plan:a']
                else:presentation['cards'][1]['stage_ids']=['unknown']
                with self.assertRaises(ACGError):build_story_model(reader,presentation)

    def test_branches_cannot_form_cycles_or_reference_unknown_parents(self):
        for parent in ('branch','unknown'):
            reader, presentation = story_fixture()
            presentation['cards'][0]['parent_id']=parent
            with self.assertRaises(ACGError):build_story_model(reader,presentation)

    def test_outcomes_require_in_scope_source_ids_and_explicit_tones(self):
        for result in ({'tone':'gain','text':'No source'},
                       {'tone':'gain','text':'Wrong stage','source_ids':['output:b']},
                       {'tone':'passed','text':'Invented status','source_ids':['output:a']}):
            reader, presentation = story_fixture()
            presentation['cards'][0]['results']=[result]
            with self.assertRaises(ACGError):build_story_model(reader,presentation)

    def test_html_does_not_execute_source_markup_or_reexpand_tokens(self):
        reader, presentation = story_fixture()
        presentation['cards'][0]['title']='</script><img src=x onerror=alert(1)> __STYLE__'
        document = render_story_html(build_story_model(reader,presentation),title='<title> __DATA__')
        self.assertNotIn('<img src=x',document)
        self.assertIn('\\u003c/script>',document)
        self.assertIn('__STYLE__',document)
        self.assertIn('&lt;title&gt; __DATA__',document)
        self.assertIn("default-src 'none'",document)

    def test_malformed_annotations_fail_with_actionable_errors(self):
        for broken in ([],{}, {'version':'case-story-0.1','source_sha256':'a'*64,'cards':[None]}):
            reader, _ = story_fixture()
            with self.assertRaises(ACGError):build_story_model(reader,broken)


if __name__ == '__main__':
    unittest.main()
