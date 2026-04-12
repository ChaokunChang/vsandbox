from __future__ import annotations

import csv
import json
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .barrier import trace_command_has_pip_install, trace_command_is_python_barrier


@dataclass(frozen=True)
class TraceOpportunity:
    trace_id: str
    trace_path: str
    step_index: int
    command: str
    install_visible_block_s: float | None
    barrier_command: str | None
    slack_to_barrier_s: float | None
    estimated_saved_s: float | None
    residual_barrier_stall_s: float | None


@dataclass(frozen=True)
class ReplaySummary:
    trace_count: int
    bash_command_count: int
    pip_install_count: int
    traces_with_pip_install: int
    opportunities_with_barrier: int
    opportunities_with_savings: int
    total_estimated_saved_s: float
    median_estimated_saved_s: float | None
    p75_estimated_saved_s: float | None
    p90_estimated_saved_s: float | None
    median_install_visible_block_s: float | None
    median_slack_to_barrier_s: float | None


class TraceReplayAnalyzer:
    def __init__(self, traces: str | Path, *, limit: int | None = None) -> None:
        self.traces = Path(traces)
        self.limit = limit

    def analyze(self) -> tuple[ReplaySummary, list[TraceOpportunity]]:
        opportunities: list[TraceOpportunity] = []
        trace_count = 0
        bash_count = 0
        traces_with_pip: set[str] = set()
        pip_install_count = 0

        for trace_path in self._iter_trace_paths():
            trace_count += 1
            try:
                payload = json.loads(trace_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            bash_events = list(_bash_events(payload))
            bash_count += len(bash_events)
            trace_has_pip = False
            for event_index, event in enumerate(bash_events):
                if not trace_command_has_pip_install(event.command):
                    continue
                trace_has_pip = True
                pip_install_count += 1
                opportunity = self._analyze_install(trace_path, payload, bash_events, event_index)
                opportunities.append(opportunity)
            if trace_has_pip:
                traces_with_pip.add(trace_path.name)

        savings = [item.estimated_saved_s for item in opportunities if item.estimated_saved_s is not None]
        installs = [item.install_visible_block_s for item in opportunities if item.install_visible_block_s is not None]
        slacks = [item.slack_to_barrier_s for item in opportunities if item.slack_to_barrier_s is not None]
        summary = ReplaySummary(
            trace_count=trace_count,
            bash_command_count=bash_count,
            pip_install_count=pip_install_count,
            traces_with_pip_install=len(traces_with_pip),
            opportunities_with_barrier=sum(1 for item in opportunities if item.barrier_command is not None),
            opportunities_with_savings=len(savings),
            total_estimated_saved_s=sum(savings),
            median_estimated_saved_s=_median(savings),
            p75_estimated_saved_s=_percentile(savings, 75),
            p90_estimated_saved_s=_percentile(savings, 90),
            median_install_visible_block_s=_median(installs),
            median_slack_to_barrier_s=_median(slacks),
        )
        return summary, opportunities

    def _iter_trace_paths(self) -> Iterable[Path]:
        if self.traces.is_file():
            yield self.traces
            return
        if not self.traces.is_dir():
            raise FileNotFoundError(f"trace path does not exist: {self.traces}")
        paths = sorted(self.traces.glob("*-traj.json"))
        if not paths:
            paths = sorted(self.traces.glob("**/trajectory.json"))
        for index, path in enumerate(paths):
            if self.limit is not None and index >= self.limit:
                break
            yield path

    def _analyze_install(
        self,
        trace_path: Path,
        payload: dict[str, Any],
        bash_events: list["_BashEvent"],
        event_index: int,
    ) -> TraceOpportunity:
        event = bash_events[event_index]
        visible_block = _visible_block_from_previous_step(payload, event.step_index, event.timestamp_s)
        barrier = _next_python_barrier(bash_events, event_index + 1)
        slack: float | None = None
        saved: float | None = None
        residual: float | None = None
        if barrier is not None and event.timestamp_s is not None and barrier.timestamp_s is not None:
            slack = max(0.0, barrier.timestamp_s - event.timestamp_s)
            if visible_block is not None:
                saved = min(visible_block, slack)
                residual = max(0.0, visible_block - slack)
        return TraceOpportunity(
            trace_id=_trace_id(trace_path, payload),
            trace_path=str(trace_path),
            step_index=event.step_index,
            command=_one_line(event.command),
            install_visible_block_s=visible_block,
            barrier_command=_one_line(barrier.command) if barrier is not None else None,
            slack_to_barrier_s=slack,
            estimated_saved_s=saved,
            residual_barrier_stall_s=residual,
        )


@dataclass(frozen=True)
class _BashEvent:
    step_index: int
    timestamp_s: float | None
    command: str


def _bash_events(payload: dict[str, Any]) -> Iterable[_BashEvent]:
    steps = payload.get("steps")
    if not isinstance(steps, list):
        return
    for step_index, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        timestamp_s = _parse_timestamp(step.get("timestamp"))
        tool_calls = step.get("tool_calls")
        if not isinstance(tool_calls, list):
            continue
        for tool_call in tool_calls:
            if not isinstance(tool_call, dict) or tool_call.get("function_name") != "Bash":
                continue
            arguments = tool_call.get("arguments")
            if not isinstance(arguments, dict):
                continue
            command = arguments.get("command")
            if isinstance(command, str):
                yield _BashEvent(step_index=step_index, timestamp_s=timestamp_s, command=command)


def _visible_block_from_previous_step(
    payload: dict[str, Any],
    step_index: int,
    timestamp_s: float | None,
) -> float | None:
    if timestamp_s is None:
        return None
    steps = payload.get("steps")
    if not isinstance(steps, list):
        return None
    for previous in reversed(steps[:step_index]):
        if not isinstance(previous, dict):
            continue
        previous_ts = _parse_timestamp(previous.get("timestamp"))
        if previous_ts is not None:
            return max(0.0, timestamp_s - previous_ts)
    return None


def _next_python_barrier(events: list[_BashEvent], start: int) -> _BashEvent | None:
    for event in events[start:]:
        if trace_command_is_python_barrier(event.command):
            return event
    return None


def _parse_timestamp(value: object) -> float | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(raw).timestamp()
    except ValueError:
        return None


def _trace_id(trace_path: Path, payload: dict[str, Any]) -> str:
    session = payload.get("session_id")
    if isinstance(session, str) and session:
        return session
    return trace_path.name.removesuffix("-traj.json")


def _one_line(value: str) -> str:
    return " ".join(value.split())


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def _percentile(values: list[float], percentile: int) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = round((len(ordered) - 1) * (percentile / 100.0))
    return ordered[int(index)]


def analysis_to_json(summary: ReplaySummary, opportunities: list[TraceOpportunity]) -> str:
    return json.dumps(
        {
            "summary": asdict(summary),
            "opportunities": [asdict(item) for item in opportunities],
        },
        indent=2,
        sort_keys=True,
    )


def write_opportunities_csv(path: str | Path, opportunities: list[TraceOpportunity]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(asdict(opportunities[0]).keys()) if opportunities else [])
        if opportunities:
            writer.writeheader()
            for item in opportunities:
                writer.writerow(asdict(item))

