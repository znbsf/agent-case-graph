from __future__ import annotations

import unittest

from agent_case_graph.model import ACGError, parse_events


class LedgerJsonDepthTests(unittest.TestCase):
    def test_deep_json_is_a_line_numbered_protocol_error(self):
        synthetic_json = "[" * 20_000 + "0" + "]" * 20_000
        with self.assertRaisesRegex(ACGError, r"^line 2: invalid JSON:") as raised:
            parse_events("\n" + synthetic_json)
        self.assertIsInstance(raised.exception.__cause__, RecursionError)


if __name__ == "__main__":
    unittest.main()
