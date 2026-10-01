from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_case_graph.model import ACGError, load_events


class LedgerJsonDepthTests(unittest.TestCase):
    def test_deep_json_is_a_line_numbered_protocol_error(self):
        synthetic_json = "[" * 20_000 + "0" + "]" * 20_000
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "events.jsonl"
            ledger.write_text("\n" + synthetic_json, encoding="utf-8")
            with self.assertRaisesRegex(ACGError, r"^line 2: invalid JSON:") as raised:
                load_events(ledger)
        self.assertIsInstance(raised.exception.__cause__, RecursionError)


if __name__ == "__main__":
    unittest.main()
