from __future__ import annotations

import argparse
import json
import shlex
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

from .graph import JobResult, RealizationNode
from .replay import TraceReplayAnalyzer, analysis_to_json, write_opportunities_csv
from .runtime import VirtualSandbox
from .whatif import FutureBenefitAnalyzer, summary_to_json as whatif_summary_to_json


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vsandbox")
    subparsers = parser.add_subparsers(dest="command_name", required=True)

    demo_parser = subparsers.add_parser("demo", help="run a deterministic deferred-pip demo")
    demo_parser.add_argument("--delay", type=float, default=0.5, help="fake realization delay in seconds")

    run_parser = subparsers.add_parser("run", help="run one command in a fresh sandbox")
    run_parser.add_argument("--workspace", type=Path, required=True)
    run_parser.add_argument("command", nargs=argparse.REMAINDER)

    replay_parser = subparsers.add_parser("replay", help="analyze ATIF trajectories")
    replay_parser.add_argument("--traces", type=Path, required=True)
    replay_parser.add_argument("--limit", type=int, default=None)
    replay_parser.add_argument("--json", action="store_true", help="emit full JSON output")
    replay_parser.add_argument("--csv", type=Path, default=None, help="write per-opportunity CSV")

    whatif_parser = subparsers.add_parser("whatif", help="estimate additional deferred-readiness mechanisms")
    whatif_parser.add_argument("--traces", type=Path, required=True)
    whatif_parser.add_argument("--limit", type=int, default=None)

    args = parser.parse_args(argv)
    if args.command_name == "demo":
        return _demo(args.delay)
    if args.command_name == "run":
        return _run_once(args.workspace, args.command)
    if args.command_name == "replay":
        return _replay(args.traces, limit=args.limit, emit_json=args.json, csv_path=args.csv)
    if args.command_name == "whatif":
        return _whatif(args.traces, limit=args.limit)
    parser.error("unknown command")
    return 2


def _demo(delay: float) -> int:
    with tempfile.TemporaryDirectory(prefix="vsandbox-demo-") as tmp:
        workspace = Path(tmp)

        def fake_realizer(node: RealizationNode) -> JobResult:
            time.sleep(delay)
            (workspace / "demo_pkg.py").write_text("VALUE = 'realized'\n", encoding="utf-8")
            return JobResult(0, stdout="fake package realized\n")

        sandbox = VirtualSandbox.create(workspace=workspace, use_venv=False, pip_realizer=fake_realizer)
        started = time.monotonic()
        install = sandbox.run("python -m pip install demo-pkg")
        time.sleep(delay / 2.0)
        sandbox.write_file("script.py", "import demo_pkg\nprint(demo_pkg.VALUE)\n")
        execution = sandbox.run("python script.py")
        total = time.monotonic() - started
        payload = {
            "workspace": str(workspace),
            "install": asdict(install),
            "execution": asdict(execution),
            "total_elapsed_s": total,
            "status": sandbox.status(),
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        sandbox.shutdown()
    return 0


def _run_once(workspace: Path, command_parts: list[str]) -> int:
    if command_parts and command_parts[0] == "--":
        command_parts = command_parts[1:]
    if not command_parts:
        raise SystemExit("vsandbox run requires a command after --")
    command = command_parts[0] if len(command_parts) == 1 else shlex.join(command_parts)
    sandbox = VirtualSandbox.create(workspace=workspace)
    result = sandbox.run(command)
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="")
    print(json.dumps({"result": asdict(result), "status": sandbox.status()}, indent=2, sort_keys=True))
    sandbox.shutdown()
    return result.returncode


def _replay(traces: Path, *, limit: int | None, emit_json: bool, csv_path: Path | None) -> int:
    analyzer = TraceReplayAnalyzer(traces, limit=limit)
    summary, opportunities = analyzer.analyze()
    if csv_path is not None:
        write_opportunities_csv(csv_path, opportunities)
    if emit_json:
        print(analysis_to_json(summary, opportunities))
    else:
        print(json.dumps(asdict(summary), indent=2, sort_keys=True))
    return 0


def _whatif(traces: Path, *, limit: int | None) -> int:
    summary = FutureBenefitAnalyzer(traces, limit=limit).analyze()
    print(whatif_summary_to_json(summary))
    return 0
