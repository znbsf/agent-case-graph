# Contributing

Contributions are welcome when they preserve three boundaries:

1. Canonical facts come from append-only events, not visual layout.
2. Mutating actions require explicit targets, authorization, and verification.
3. Tests and examples must use synthetic, de-identified data.

## Development

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
node --test tests/workbench-layout.test.cjs
python -m compileall -q agent_case_graph
acg lint --strict examples/quickstart/events.jsonl
```

Keep changes focused and add a regression test for protocol, runtime, projector,
or renderer behavior. Do not commit caches, generated example projections,
credentials, internal issue identifiers, absolute local paths, or private
Ledgers.

## Browser checks

The runtime has no required third-party dependencies. Browser verification uses
an optional development extra, preferably in a virtual environment:

```bash
python -m pip install -e ".[browser-test]"
python -m playwright install chromium
python -m scripts.check_browser --out-dir .artifacts/browser
```

On Windows, `--channel msedge` or `--channel chrome` can use an existing browser
instead of downloading Chromium. The test opens the generated HTML from disk
with network access disabled. It exercises all views, source/details selection,
keyboard activation and both locales at 390x844, and saves screenshots plus a
JSON result. Fixtures and CI artifacts must remain synthetic and de-identified.

The default `graph.html` key-path graph, auxiliary `reader.html`, and `workbench.html` are checked separately.
Workbench checks cover stage expansion, canonical edge witnesses, neighbor
focus, zoom, URL restoration, search, source pagination and both locales at
320/390/768/1440px. Existing fixed-card regressions target `workbench-legacy.html`.
Pure geometry tests use Node 20+ with no installed npm dependencies. For an
already generated model, run `node scripts/check_workbench_geometry.cjs
path/to/workbench-model.json` to check coverage and route geometry with synthetic
card sizes. That output is not a substitute for browser font/layout inspection.
Graph checks cover scoped expansion, keyboard navigation, editorial branches,
branch toggling, and responsive layouts. Presentation annotations must bind to
the source ledger hash and preserve every stage; tones are not runtime verdicts.
Reader checks cover stage navigation, collapsed evidence, both locales and
320/390/768/1440px widths. Projection tests must preserve source provenance,
counterevidence, unknown coverage and stage result ownership. Keep private
reconstructed cases outside public fixtures and CI artifacts.

The CI matrix covers Ubuntu and Windows on Python 3.11, 3.12 and 3.13; browser
checks run separately on Ubuntu. Local success does not establish a remote CI
result or a real-agent performance improvement.
