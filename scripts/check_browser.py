"""Exercise generated, offline HTML with public synthetic data in a real browser.

Install the optional browser-test extra and Chromium before running this module.
Use --channel msedge or chrome to reuse a locally installed browser.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from agent_case_graph.ledger import atomic_write_text, read_ledger_snapshot
from agent_case_graph.lint import lint_graph
from agent_case_graph.localization import load_display_locales
from agent_case_graph.projector import project_events
from agent_case_graph.renderer import write_projection
from agent_case_graph.story_graph import build_story_model, render_story_html


def check_evidence_workbench(page, output: Path, checks: list[dict]) -> None:
    """New workbench behavior; the legacy renderer is checked separately below."""
    model = json.loads((output / 'workbench-model.json').read_text(encoding='utf-8'))
    expect(page.locator('#graphNodes .graph-node')).to_have_count(len(model['groups']))
    expect(page.locator('#detailsPanel')).to_be_hidden()
    expect(page.locator('#timeline .event')).to_have_count(0)
    expect(page.locator('#coverageNotice')).to_contain_text('合成示例')
    page.locator('#graphNodes .node-expand').first.click()
    expect(page.locator('[data-view="workflow"]')).to_have_attribute('aria-selected', 'true')
    scope_id = page.locator('#scopeSelect').input_value()
    scope = next(s for s in model['scopes'] if s['id'] == scope_id)
    expect(page.locator('#graphNodes .graph-node')).to_have_count(len(scope['related_node_ids']))
    page.locator('#graphNodes .node-button').first.focus()
    page.locator('#graphNodes .node-button').first.press('Enter')
    expect(page.locator('#detailsPanel')).to_be_visible()
    selected_id = page.locator('#details .node-id').first.inner_text()
    expect(page.locator('#details .source-list')).to_be_visible()
    page.locator('#focusButton').click()
    focus_nodes = page.locator('#graphNodes .graph-node').count()
    assert focus_nodes <= len(scope['related_node_ids'])
    expect(page.locator('#clearFocus')).to_be_visible()
    page.locator('#clearFocus').click()
    expect(page.locator('#graphNodes .graph-node')).to_have_count(len(scope['related_node_ids']))
    page.locator('#zoomIn').click()
    expect(page.locator('#zoomReset')).to_have_text('120%')
    assert '1.2' in page.locator('#graphWorld').get_attribute('style')
    page.locator('#zoomReset').click()
    expect(page.locator('#zoomReset')).to_have_text('100%')
    page.locator('#fitButton').click()
    assert int(page.locator('#zoomReset').inner_text().removesuffix('%')) <= 100
    page.locator('#zoomReset').click()
    page.locator('#scopeSelect').select_option('all')
    expect(page.locator('#detailsPanel')).to_be_hidden()
    page.locator('[data-view="overview"]').click()
    # Make all summary edges visible, then verify the exact source witnesses.
    page.locator('.filters summary').click()
    page.locator('#showStructure').check()
    page.locator('#showEvidence').check()
    summary = model['group_edges'][0]
    page.locator(f'[data-edge-id="{summary["id"]}"]').focus()
    page.locator(f'[data-edge-id="{summary["id"]}"]').press('Enter')
    expect(page.locator('#details .node-id').first).to_have_text(summary['id'])
    expect(page.locator('#details .detail-relation')).to_have_count(2 + len(summary['source_edge_ids']))
    page.reload()
    expect(page.locator('#details .node-id').first).to_have_text(summary['id'])
    page.locator('#details .detail-relation').nth(2).click()
    expect(page.locator('#details .node-id').first).to_have_text(summary['source_edge_ids'][0])
    page.locator('#basisButton').click()
    expect(page.locator('.basis-item')).to_have_count(4)
    expect(page.locator('#details')).to_contain_text('preprint')
    page.locator('#closeDetails').click()
    page.locator('#searchInput').fill(selected_id)
    page.locator('#searchResults button').first.click()
    expect(page.locator('#details .node-id').first).to_have_text(selected_id)
    expect(page.locator('#clearFocus')).to_be_visible()
    page.locator('#clearFocus').click()
    page.locator('#searchInput').fill('')
    for view in ('overview', 'workflow', 'evidence', 'sequence', 'trace'):
        page.locator(f'[data-view="{view}"]').click()
        if view == 'trace':
            expect(page.locator('#timeline .event')).to_have_count(min(40, len(model['trace'])))
            expect(page.locator('#canvasShell')).to_be_hidden()
        elif view == 'sequence':
            expect(page.locator('#graphNodes .sequence-step')).not_to_have_count(0)
            assert page.locator('#graphSvg').get_attribute('viewBox')
        else:
            expect(page.locator('#graphNodes .graph-node')).not_to_have_count(0)
    page.locator('[data-view="overview"]').click()
    page.locator('#closeDetails').click()
    page.screenshot(path=str(output / 'workbench-desktop.png'), full_page=True)
    for width in (320, 390, 768, 1440):
        page.set_viewport_size({'width': width, 'height': 900})
        for locale in ('zh-CN', 'en-US'):
            page.locator('#languageSelect').select_option(locale)
            for view in ('overview', 'workflow', 'evidence', 'sequence', 'trace'):
                page.locator(f'[data-view="{view}"]').click()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (width, locale, view)
    page.set_viewport_size({'width': 390, 'height': 844})
    page.locator('[data-view="overview"]').click()
    page.screenshot(path=str(output / 'workbench-mobile.png'), full_page=True)
    page.set_viewport_size({'width': 1440, 'height': 1000})
    checks.append({'check': 'workbench_scopes_zoom_provenance_hash_search_and_responsive_locales', 'passed': True})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=Path(".artifacts/browser"))
    parser.add_argument("--channel", choices=("chrome", "msedge"))
    args = parser.parse_args()
    output = args.out_dir.resolve()
    ledger = Path(__file__).resolve().parents[1] / "examples/quickstart/events.jsonl"
    events, digest = read_ledger_snapshot(ledger)
    if any(event["provenance"]["capture_mode"] != "synthetic" for event in events):
        raise ValueError("Browser fixture must be public synthetic data")
    graph = project_events(events, ledger_path=ledger, ledger_sha256=digest)
    write_projection(
        output, graph=graph, events=events, findings=lint_graph(graph),
        title="Synthetic browser verification", display_locales=load_display_locales(ledger),
    )
    errors: list[str] = []
    external_requests: list[str] = []
    checks: list[dict] = []
    report = {"capture_mode": "synthetic", "source_sha256": digest,
              "checks": checks, "errors": errors, "external_requests": external_requests}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel=args.channel)
        report["browser_version"] = browser.version
        context = browser.new_context(offline=True, viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
        page.on("request", lambda request: external_requests.append(request.url)
                if request.url.startswith(("http://", "https://")) else None)
        try:
            page.goto((output / "graph.html").as_uri())
            expect(page.locator('#storyTitle')).to_be_visible()
            expect(page.locator('.map-card')).not_to_have_count(0)
            expect(page.locator('#coverageNotice')).to_contain_text('合成示例')
            expect(page.locator('#localDetail')).to_have_count(0)
            expect(page.locator('#timeline')).to_have_count(0)
            page.locator('.card-open').first.focus()
            page.locator('.card-open').first.press('Enter')
            expect(page.locator('#localDetail .evidence-node')).not_to_have_count(0)
            page.keyboard.press('Escape')
            expect(page.locator('#localDetail')).to_have_count(0)
            for width in (320,390,768,1440):
                page.set_viewport_size({'width':width,'height':900})
                for locale in ('zh-CN','en-US'):
                    page.locator('#storyLanguage').select_option(locale)
                    expect(page.locator('html')).to_have_attribute('lang',locale)
                    page.locator('.card-open').first.click()
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    page.keyboard.press('Escape')
            page.set_viewport_size({'width':1440,'height':1000})
            page.screenshot(path=str(output/'graph-desktop.png'),full_page=True)
            checks.append({'check':'graph_default_keyboard_local_expansion_and_responsive_locales','passed':True})

            # An explicitly authored, public synthetic branch exercises the same
            # layout as private cases without adding those cases to CI artifacts.
            review = json.loads((output/'review-model.json').read_text(encoding='utf-8'))
            authored_cards = [dict(id=stage['id'],stage_ids=[stage['id']],title=stage['title'],
                                   parent_id=review['stages'][0]['id'] if i else None)
                              for i,stage in enumerate(review['stages'])]
            authored_cards.append(dict(id='synthetic:branch',parent_id=authored_cards[0]['id'],
                                       node_ids=[review['stages'][0]['member_ids'][0]],title='合成旁支 / Synthetic branch'))
            authored = build_story_model(review,dict(version='case-story-0.1',source_sha256=digest,cards=authored_cards))
            atomic_write_text(output/'story-authored.html',render_story_html(authored,title='Synthetic branch QA'))
            page.goto((output/'story-authored.html').as_uri())
            expect(page.locator('.branch-card')).not_to_have_count(0)
            expect(page.locator('.map-wire.branch')).to_have_count(len(authored_cards)-1)
            branch = page.locator('[data-card-id="synthetic:branch"] .card-open')
            branch.click()
            expect(branch).to_have_attribute('aria-expanded','true')
            page.locator('#showBranches').uncheck()
            expect(page.locator('.branch-card')).to_have_count(0)
            expect(page.locator('#localDetail')).to_have_count(0)
            page.locator('#showBranches').check()
            for width in (320,390,768,1440):
                page.set_viewport_size({'width':width,'height':900})
                branch.click()
                expect(page.locator('#localDetail')).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.keyboard.press('Escape')
            checks.append({'check':'source_bound_branches_toggle_and_expansion','passed':True})
            page.locator('#readerLink').click()
            expect(page.locator('#readerContent h1')).to_be_visible()
            expect(page.locator('#readerContent .path-item')).not_to_have_count(0)
            expect(page.locator('#coverageNotice')).to_contain_text('合成示例')
            expect(page.locator('#timeline')).to_have_count(0)
            page.locator('#readerContent .path-heading a').first.click()
            expect(page.locator('.result-section')).to_be_visible()
            expect(page.locator('.stage-evidence')).not_to_have_attribute('open','')
            page.locator('.stage-evidence summary').click()
            expect(page.locator('.stage-evidence')).to_have_attribute('open','')
            for width in (320,390,768,1440):
                page.set_viewport_size({'width':width,'height':900})
                for locale in ('zh-CN','en-US'):
                    page.locator('#readerLanguage').select_option(locale)
                    expect(page.locator('html')).to_have_attribute('lang',locale)
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.set_viewport_size({'width':1440,'height':1000})
            page.locator('#brand').click()
            page.screenshot(path=str(output/'reader-desktop.png'), full_page=True)
            checks.append({'check':'reader_default_scoped_evidence_and_responsive_locales','passed':True})
            page.locator('#advancedLink').click()
            check_evidence_workbench(page, output, checks)
            # Preserve existing renderer regression checks without confusing
            # the old fixed-card technical view with the new default workbench.
            page.goto((output / 'workbench-legacy.html').as_uri())
            expect(page.locator('.view-tab[aria-selected="true"]')).to_have_attribute("data-view", "overview")
            expect(page.locator("#timeline .event")).to_have_count(len(events))
            label_widths = page.evaluate("""() => {
                const samples = ['保留原生输入并验证显示交付抖动，不能把平均吞吐当作显示稳定',
                    'WWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWW',
                    '👩‍💻 👩‍💻 👩‍💻 long mixed 中文标题与结果边界'];
                const group = el('g', {class:'node',visibility:'hidden'});
                const probe = el('text', {class:'label'}); group.append(probe); svg.append(group);
                try { return samples.map(value => ({value, lines:wrap(value,26).map(line => {
                    probe.textContent=line; return {line,width:probe.getComputedTextLength()};
                })})); } finally { group.remove(); }
            }""")
            for sample in label_widths:
                assert 1 <= len(sample['lines']) <= 2, sample
                assert all(line['width'] <= 152.01 for line in sample['lines']), sample
            checks.append({"check":"cjk_wide_and_emoji_labels_fit_cards", "passed":True})
            for view in ("overview", "sequence", "workflow", "evidence", "trace"):
                tab = page.locator(f'.view-tab[data-view="{view}"]')
                tab.click()
                expect(tab).to_have_attribute("aria-selected", "true")
                if view == "sequence":
                    expect(page.locator("#sequenceControls")).to_be_visible()
                    assert page.locator("#sequenceScopeSelect option").count() > 0
                    assert page.locator("#graphSvg .sequence-step").count() > 0
                elif view == "trace":
                    expect(page.locator("#sequenceControls")).to_be_hidden()
                    expect(page.locator("#graphSvg .trace-card")).to_have_count(len(events))
                else:
                    expect(page.locator("#sequenceControls")).to_be_hidden()
                    assert page.locator("#graphSvg .node").count() > 0
                checks.append({"check": "view_switch", "view": view, "passed": True})

            page.locator('.view-tab[data-view="workflow"]').click()
            node = page.locator('#graphSvg .node[data-node-id="action:DEMO-001:select"]')
            node.click()
            expect(page.locator("#details .node-id")).to_have_text("action:DEMO-001:select")
            expect(page.locator("#timeline .event.active")).to_have_count(1)
            # Keyboard selection and source trace selection must reach the same drawer.
            node.focus()
            node.press("Enter")
            event_index = next(i for i, event in enumerate(events)
                               if event.get("node", {}).get("type") == "Observation")
            page.locator("#timeline .event").nth(event_index).click()
            expect(page.locator("#details .node-id")).to_have_text(events[event_index]["node"]["id"])
            checks.append({"check": "node_trace_details_linkage", "passed": True})
            page.screenshot(path=str(output / "desktop.png"), full_page=True)

            for locale in ("en-US", "zh-CN"):
                page.locator("#languageSelect").select_option(locale)
                expect(page.locator("html")).to_have_attribute("lang", locale)
                page.set_viewport_size({"width": 390, "height": 844})
                for view in ("overview", "sequence", "workflow", "evidence", "trace"):
                    page.locator(f'.view-tab[data-view="{view}"]').click()
                    dimensions = page.evaluate("({width:innerWidth, content:document.documentElement.scrollWidth})")
                    assert dimensions["content"] <= dimensions["width"], (locale, view, dimensions)
                    expect(page.locator(".details-panel")).to_be_visible()
                checks.append({"check": "mobile_all_views", "locale": locale, "passed": True})
            page.locator('.view-tab[data-view="workflow"]').click()
            page.locator('#graphSvg .node[data-node-id="action:DEMO-001:select"]').click()
            expect(page.locator("#details .node-id")).to_have_text("action:DEMO-001:select")
            page.screenshot(path=str(output / "mobile.png"), full_page=True)
            assert not errors, errors
            assert not external_requests, external_requests
            report["passed"] = True
        except Exception as error:
            report["passed"] = False
            report["failure"] = str(error)
            page.screenshot(path=str(output / "failure.png"), full_page=True)
            raise
        finally:
            atomic_write_text(output / "browser-check.json", json.dumps(report, ensure_ascii=False, indent=2) + "\n")
            browser.close()
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
