from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from vsandbox.replay import TraceReplayAnalyzer


class TraceReplayAnalyzerTests(unittest.TestCase):
    def test_estimates_deferred_pip_savings_from_trace_timestamps(self) -> None:
        payload = {
            "schema_version": "ATIF-v1.2",
            "session_id": "session-1",
            "steps": [
                {"source": "user", "timestamp": "2026-02-07T00:00:00.000Z", "message": "task"},
                {
                    "source": "agent",
                    "timestamp": "2026-02-07T00:00:02.000Z",
                    "tool_calls": [
                        {
                            "function_name": "Bash",
                            "tool_call_id": "tool-1",
                            "arguments": {"command": "pip install pandas"},
                        }
                    ],
                },
                {
                    "source": "agent",
                    "timestamp": "2026-02-07T00:00:07.000Z",
                    "tool_calls": [
                        {
                            "function_name": "Bash",
                            "tool_call_id": "tool-2",
                            "arguments": {"command": "ls -la"},
                        }
                    ],
                },
                {
                    "source": "agent",
                    "timestamp": "2026-02-07T00:00:12.000Z",
                    "tool_calls": [
                        {
                            "function_name": "Bash",
                            "tool_call_id": "tool-3",
                            "arguments": {"command": "python -c 'import pandas'"},
                        }
                    ],
                },
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            trace = Path(tmp, "sample-traj.json")
            trace.write_text(json.dumps(payload), encoding="utf-8")
            summary, opportunities = TraceReplayAnalyzer(trace).analyze()

        self.assertEqual(summary.trace_count, 1)
        self.assertEqual(summary.bash_command_count, 3)
        self.assertEqual(summary.pip_install_count, 1)
        self.assertEqual(summary.traces_with_pip_install, 1)
        self.assertEqual(summary.opportunities_with_savings, 1)
        opportunity = opportunities[0]
        self.assertEqual(opportunity.install_visible_block_s, 2.0)
        self.assertEqual(opportunity.slack_to_barrier_s, 10.0)
        self.assertEqual(opportunity.estimated_saved_s, 2.0)
        self.assertEqual(opportunity.residual_barrier_stall_s, 0.0)


if __name__ == "__main__":
    unittest.main()

