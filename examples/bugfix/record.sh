#!/usr/bin/env bash
# Record a small bug-fix session with the acg CLI, then project it.
# Usage: bash examples/bugfix/record.sh [out-dir]
# Set ACG="python -m agent_case_graph" to run without installing the package.
set -euo pipefail

OUT=${1:-examples/bugfix/generated}
ACG=${ACG:-acg}
LEDGER="$OUT/events.jsonl"
CASE=BUGFIX-001
RUN=run:BUGFIX-001:001
mkdir -p "$OUT"
rm -f "$LEDGER" "$LEDGER.lock"

# Every record carries the same case, run and honesty label.
rec() { $ACG "$@" --ledger "$LEDGER" --case-id "$CASE" --run-id "$RUN" --capture-mode synthetic --source-ref example:bugfix >/dev/null; }
node() { rec record-node --node-id "$1" --node-type "$2" --label "$3" --attrs "${4:-{\}}"; }
edge() { rec record-edge --edge-id "$1" --edge-type "$2" --from-id "$3" --to-id "$4"; }
state() { rec record-state --subject-id "case:$CASE" --from-state "$1" --to-state "$2" --reason "$3"; }

# 1. Open the case: graph declaration, Case node, Run node.
$ACG init-case --ledger "$LEDGER" --case-id "$CASE" --run-id "$RUN" \
  --title "test_parse_date fails only on Windows CI" --capture-mode synthetic >/dev/null

# 2. What we want and what we saw.
state intake observe "CI is red on one platform"
node goal:green Goal "Make test_parse_date pass on every platform"
edge e:goal contains "$RUN" goal:green
node obs:ci Observation "CI log: ValueError: time data '03 Mär 2026' does not match '%d %b %Y'" '{"status":"confirmed"}'
edge e:obs contains "$RUN" obs:ci

# 3. A hypothesis, explained (not yet supported) by the observation.
state observe analyze "Error text shows a localized month name"
node claim:locale Claim "Root cause: strptime %b depends on the runner locale" '{"status":"proposed"}'
edge e:claim contains "$RUN" claim:locale
edge e:explains explains obs:ci claim:locale

# 4. Plan: patch first, verify second. Only runtime_managed nodes enter the runtime.
state analyze plan "Fix is local to the parser"
node act:patch Action "Parse month names from a fixed English table" '{"runtime_managed":true,"status":"pending","mutating":false}'
node ver:pytest Verification "Run pytest on ubuntu and windows" '{"runtime_managed":true,"status":"pending","mutating":false}'
edge e:act contains "$RUN" act:patch
edge e:ver contains "$RUN" ver:pytest
edge e:order precedes act:patch ver:pytest
edge e:checks checks ver:pytest claim:locale
state plan execute "Plan accepted"

echo "== before work =="
$ACG next-actions "$LEDGER"

# 5. Do the work through gated checkpoints.
$ACG step-status --ledger "$LEDGER" --node-id act:patch --status running --reason "editing dates.py" >/dev/null
$ACG step-status --ledger "$LEDGER" --node-id act:patch --status completed --reason "patch applied" >/dev/null
echo "== after patch =="
$ACG next-actions "$LEDGER"
$ACG step-status --ledger "$LEDGER" --node-id ver:pytest --status running --reason "CI matrix started" >/dev/null
$ACG step-status --ledger "$LEDGER" --node-id ver:pytest --status completed --reason "both platforms green" >/dev/null

# 6. The claim gate refuses confirmation until completed evidence explicitly supports it.
echo "== confirm without evidence =="
if $ACG claim-status --ledger "$LEDGER" --claim-id claim:locale --status confirmed --capture-mode synthetic >/dev/null; then
  echo "unexpected: claim confirmed without support" >&2; exit 1
fi
edge e:supports supports ver:pytest claim:locale
state execute verify "Verification finished"
$ACG claim-status --ledger "$LEDGER" --claim-id claim:locale --status confirmed --capture-mode synthetic >/dev/null
echo "== claim confirmed =="

$ACG lint --strict "$LEDGER"
$ACG project "$LEDGER" --out-dir "$OUT" --title "Bug fix: locale-dependent date parsing" >/dev/null
echo "open $OUT/graph.html"
