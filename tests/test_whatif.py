from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from vsandbox.whatif import FutureBenefitAnalyzer


class FutureBenefitAnalyzerTests(unittest.TestCase):
    def test_estimates_additional_mechanism_opportunities(self) -> None:
        payload = {
            "schema_version": "ATIF-v1.6",
            "session_id": "whatif-demo",
            "steps": [
                {"source": "user", "timestamp": "2026-02-07T00:00:00.000Z", "message": "task"},
                {
                    "source": "agent",
                    "timestamp": "2026-02-07T00:00:10.000Z",
                    "tool_calls": [
                        {
                            "function_name": "bash_command",
                            "arguments": {"keystrokes": "apt-get install -y libhdf5-dev\n", "duration": 5.0},
                        },
                        {
                            "function_name": "bash_command",
                            "arguments": {"keystrokes": "ls -la\n", "duration": 1.0},
                        },
                    ],
                },
                {
                    "source": "agent",
                    "timestamp": "2026-02-07T00:00:30.000Z",
                    "tool_calls": [
                        {
                            "function_name": "bash_command",
                            "arguments": {"keystrokes": "python -c 'print(1)'\n", "duration": 1.0},
                        }
                    ],
                },
                {
                    "source": "agent",
                    "timestamp": "2026-02-07T00:00:40.000Z",
                    "tool_calls": [
                        {
                            "function_name": "bash_command",
                            "arguments": {
                                "keystrokes": "git clone https://example.invalid/repo.git\n",
                                "duration": 8.0,
                            },
                        }
                    ],
                },
                {
                    "source": "agent",
                    "timestamp": "2026-02-07T00:01:00.000Z",
                    "tool_calls": [
                        {
                            "function_name": "bash_command",
                            "arguments": {"keystrokes": "make test\n", "duration": 2.0},
                        }
                    ],
                },
                {
                    "source": "agent",
                    "timestamp": "2026-02-07T00:01:10.000Z",
                    "tool_calls": [
                        {
                            "function_name": "bash_command",
                            "arguments": {"keystrokes": "pip install pandas\n", "duration": 10.0},
                        }
                    ],
                },
                {
                    "source": "agent",
                    "timestamp": "2026-02-07T00:01:25.000Z",
                    "tool_calls": [
                        {
                            "function_name": "bash_command",
                            "arguments": {"keystrokes": "python -c 'import pandas'\n", "duration": 1.0},
                        }
                    ],
                },
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp, "whatif-demo")
            task_dir.mkdir()
            trace = task_dir / "trajectory.json"
            trace.write_text(json.dumps(payload), encoding="utf-8")
            summary = FutureBenefitAnalyzer(tmp).analyze()

        mechanisms = {item.name: item for item in summary.mechanisms}
        self.assertEqual(summary.trace_count, 1)
        self.assertEqual(summary.bash_command_count, 7)
        self.assertEqual(mechanisms["apt_install"].event_count, 1)
        self.assertEqual(mechanisms["apt_install"].total_estimated_saved_s, 5.0)
        self.assertEqual(mechanisms["git_clone"].event_count, 1)
        self.assertEqual(mechanisms["git_clone"].total_estimated_saved_s, 8.0)
        self.assertEqual(mechanisms["base_fs_5s"].total_estimated_saved_s, 5.0)
        self.assertEqual(mechanisms["base_fs_15s"].total_estimated_saved_s, 10.0)
        self.assertEqual(mechanisms["pip_baseline"].event_count, 1)
        self.assertEqual(mechanisms["pip_baseline"].total_estimated_saved_s, 5.0)
        self.assertEqual(mechanisms["spec_apt_oracle"].total_estimated_saved_s, 5.0)
        self.assertEqual(mechanisms["spec_git_clone_oracle"].total_estimated_saved_s, 8.0)
        self.assertEqual(mechanisms["spec_pip_oracle"].total_estimated_saved_s, 10.0)
        self.assertEqual(mechanisms["spec_all_oracle"].total_estimated_saved_s, 23.0)
        self.assertEqual(mechanisms["fine_import_1s"].total_estimated_saved_s, 1.0)
        self.assertEqual(mechanisms["fine_import_5s"].total_estimated_saved_s, 5.0)
        self.assertEqual(mechanisms["fine_import_15s"].total_estimated_saved_s, 5.0)


if __name__ == "__main__":
    unittest.main()
