from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from vsandbox.graph import JobResult, RealizationNode
from vsandbox.runtime import VirtualSandbox


class VirtualSandboxRuntimeTests(unittest.TestCase):
    def test_pip_install_logically_commits_without_waiting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            def slow_success(node: RealizationNode) -> JobResult:
                time.sleep(0.2)
                return JobResult(0, "ok\n", "")

            sandbox = VirtualSandbox.create(workspace=tmp, use_venv=False, pip_realizer=slow_success)
            started = time.monotonic()
            result = sandbox.run("python -m pip install demo-pkg")
            elapsed = time.monotonic() - started
            self.assertEqual(result.returncode, 0)
            self.assertTrue(result.logically_committed)
            self.assertFalse(result.physical_executed)
            self.assertLess(elapsed, 0.15)
            self.assertEqual(len(sandbox.status()["jobs"]), 1)
            sandbox.shutdown()

    def test_python_import_barrier_waits_for_matching_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            def slow_success(node: RealizationNode) -> JobResult:
                time.sleep(0.08)
                return JobResult(0, "ok\n", "")

            sandbox = VirtualSandbox.create(workspace=tmp, use_venv=False, pip_realizer=slow_success)
            install = sandbox.run("pip install demo-pkg")
            Path(tmp, "demo_pkg.py").write_text("VALUE = 42\n", encoding="utf-8")
            result = sandbox.run("python -c 'import demo_pkg; print(demo_pkg.VALUE)'")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("42", result.stdout)
            self.assertGreaterEqual(result.barrier_wait_s, 0.04)
            self.assertEqual(result.jobs_waited, (install.job_id,))
            sandbox.shutdown()

    def test_nonmatching_import_does_not_wait_for_pending_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            def slow_success(node: RealizationNode) -> JobResult:
                time.sleep(0.2)
                return JobResult(0, "ok\n", "")

            sandbox = VirtualSandbox.create(workspace=tmp, use_venv=False, pip_realizer=slow_success)
            sandbox.run("pip install slow-pkg")
            Path(tmp, "other.py").write_text("VALUE = 'ready'\n", encoding="utf-8")
            result = sandbox.run("python -c 'import other; print(other.VALUE)'")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("ready", result.stdout)
            self.assertLess(result.barrier_wait_s, 0.05)
            sandbox.shutdown()

    def test_python_without_imports_waits_for_all_pending_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            def slow_success(node: RealizationNode) -> JobResult:
                time.sleep(0.08)
                return JobResult(0, "ok\n", "")

            sandbox = VirtualSandbox.create(workspace=tmp, use_venv=False, pip_realizer=slow_success)
            sandbox.run("pip install slow-pkg")
            result = sandbox.run("python -c 'print(42)'")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("42", result.stdout)
            self.assertGreaterEqual(result.barrier_wait_s, 0.04)
            sandbox.shutdown()

    def test_overlay_reads_and_execution_flush(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sandbox = VirtualSandbox.create(workspace=tmp, use_venv=False)
            sandbox.write_file("script.py", "print('from overlay')\n")
            self.assertEqual(sandbox.read_file("script.py"), "print('from overlay')\n")
            result = sandbox.run("python script.py")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("from overlay", result.stdout)
            self.assertTrue(Path(tmp, "script.py").exists())
            sandbox.shutdown()

    def test_late_pip_failure_is_reported_at_barrier(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            def failing_realizer(node: RealizationNode) -> JobResult:
                time.sleep(0.02)
                return JobResult(1, "", "no matching distribution\n")

            sandbox = VirtualSandbox.create(workspace=tmp, use_venv=False, pip_realizer=failing_realizer)
            install = sandbox.run("pip install fail-pkg")
            result = sandbox.run("python -c 'import fail_pkg'")
            self.assertEqual(result.returncode, 1)
            self.assertFalse(result.physical_executed)
            self.assertIn("deferred realization failed", result.stderr)
            self.assertIn(install.job_id or "", result.stderr)
            self.assertIn("no matching distribution", result.stderr)
            sandbox.shutdown()


if __name__ == "__main__":
    unittest.main()

