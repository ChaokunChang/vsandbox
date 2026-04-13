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
        self.assertEqual(summary.total_trace_duration_s, 12.0)
        self.assertAlmostEqual(summary.aggregate_saved_fraction or 0.0, 2.0 / 12.0)

    def test_parses_mini_swe_agent_actions_and_observation_timestamps(self) -> None:
        payload = {
            "trajectory_format": "mini-swe-agent-1.1",
            "instance_id": "demo__demo-1",
            "messages": [
                {"role": "system", "content": "system"},
                {
                    "role": "assistant",
                    "content": "<mswea_bash_command>pip install pandas</mswea_bash_command>",
                    "extra": {"actions": [{"command": "pip install pandas"}], "timestamp": 10.0},
                },
                {
                    "role": "user",
                    "content": "<returncode>0</returncode>",
                    "extra": {"returncode": 0, "raw_output": "ok", "timestamp": 14.0},
                },
                {
                    "role": "assistant",
                    "content": "<mswea_bash_command>ls</mswea_bash_command>",
                    "extra": {"actions": [{"command": "ls"}], "timestamp": 20.0},
                },
                {
                    "role": "user",
                    "content": "<returncode>0</returncode>",
                    "extra": {"returncode": 0, "raw_output": "files", "timestamp": 21.0},
                },
                {
                    "role": "assistant",
                    "content": "<mswea_bash_command>python -c 'import pandas'</mswea_bash_command>",
                    "extra": {"actions": [{"command": "python -c 'import pandas'"}], "timestamp": 30.0},
                },
                {
                    "role": "user",
                    "content": "<returncode>0</returncode>",
                    "extra": {"returncode": 0, "raw_output": "ok", "timestamp": 31.0},
                },
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp, "demo__demo-1")
            task_dir.mkdir()
            trace = task_dir / "demo__demo-1.traj.json"
            trace.write_text(json.dumps(payload), encoding="utf-8")
            summary, opportunities = TraceReplayAnalyzer(tmp).analyze()

        self.assertEqual(summary.trace_count, 1)
        self.assertEqual(summary.bash_command_count, 3)
        self.assertEqual(summary.pip_install_count, 1)
        self.assertEqual(summary.opportunity_trace_count, 1)
        opportunity = opportunities[0]
        self.assertEqual(opportunity.trace_id, "demo__demo-1")
        self.assertEqual(opportunity.install_visible_block_s, 4.0)
        self.assertEqual(opportunity.slack_to_barrier_s, 16.0)
        self.assertEqual(opportunity.estimated_saved_s, 4.0)
        self.assertEqual(summary.total_trace_duration_s, 21.0)

    def test_same_command_pip_and_python_barrier_has_no_savings(self) -> None:
        payload = {
            "trajectory_format": "mini-swe-agent-1.1",
            "instance_id": "demo__demo-2",
            "messages": [
                {
                    "role": "assistant",
                    "content": "<mswea_bash_command>pip install pytest && python -m pytest</mswea_bash_command>",
                    "extra": {
                        "actions": [{"command": "pip install pytest && python -m pytest"}],
                        "timestamp": 1.0,
                    },
                },
                {
                    "role": "user",
                    "content": "<returncode>0</returncode>",
                    "extra": {"returncode": 0, "raw_output": "ok", "timestamp": 6.0},
                },
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp, "demo__demo-2")
            task_dir.mkdir()
            trace = task_dir / "demo__demo-2.traj.json"
            trace.write_text(json.dumps(payload), encoding="utf-8")
            summary, opportunities = TraceReplayAnalyzer(tmp).analyze()

        self.assertEqual(summary.pip_install_count, 1)
        self.assertEqual(summary.opportunities_with_savings, 0)
        self.assertEqual(summary.opportunity_trace_count, 0)
        self.assertEqual(opportunities[0].slack_to_barrier_s, 0.0)
        self.assertEqual(opportunities[0].estimated_saved_s, 0.0)


if __name__ == "__main__":
    unittest.main()
