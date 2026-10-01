# Contributing

Contributions are welcome when they preserve three boundaries:

1. Canonical facts come from append-only events, not visual layout.
2. Mutating actions require explicit targets, authorization, and verification.
3. Tests and examples must use synthetic, de-identified data.

## Development

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
python -m compileall -q agent_case_graph
acg lint --strict examples/quickstart/events.jsonl
```

Keep changes focused and add a regression test for protocol, runtime, projector,
or renderer behavior. Do not commit caches, generated example projections,
credentials, internal issue identifiers, absolute local paths, or private
Ledgers.

## Project-planning adapter

Core installation remains dependency-free. Install `.[mcp]` when testing the
six read-only MCP tools. Project tests use synthetic repositories and isolated
command fixtures; real stdio tests require ordinary child-process access.

Run `python -m unittest discover -s tests -v` and, with the optional SDK, the
project planning, query, session, boundary and MCP tests. CI covers Ubuntu and
Windows on Python 3.11–3.13, public example validation and wheel construction.
Keep live trial inputs, receipts, local machine paths and generated artifacts
outside commits. Purely derived runtime advice cannot grant authorization.
