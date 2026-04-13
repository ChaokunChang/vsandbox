from __future__ import annotations

import csv
import json
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .barrier import (
    trace_command_has_pip_install,
    trace_command_has_python_barrier_after_pip,
    trace_command_is_python_barrier,
)


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
    total_trace_duration_s: float
    aggregate_saved_fraction: float | None
    opportunity_trace_count: int
    opportunity_trace_duration_s: float
    opportunity_trace_saved_fraction: float | None
    median_trace_saved_fraction: float | None
    p75_trace_saved_fraction: float | None
    p90_trace_saved_fraction: float | None
    median_opportunity_trace_saved_fraction: float | None
    p75_opportunity_trace_saved_fraction: float | None
    p90_opportunity_trace_saved_fraction: float | None
    max_opportunity_trace_saved_fraction: float | None


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
        trace_durations: dict[str, float] = {}
        saved_by_trace: dict[str, float] = {}

        for trace_path in self._iter_trace_paths():
            trace_count += 1
            try:
                payload = json.loads(trace_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            trace_key = str(trace_path)
            duration = _trace_duration_s(payload)
            if duration is not None:
                trace_durations[trace_key] = duration
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
                if opportunity.estimated_saved_s is not None:
                    saved_by_trace[trace_key] = saved_by_trace.get(trace_key, 0.0) + opportunity.estimated_saved_s
            if trace_has_pip:
                traces_with_pip.add(trace_key)

        savings = [item.estimated_saved_s for item in opportunities if item.estimated_saved_s is not None]
        installs = [item.install_visible_block_s for item in opportunities if item.install_visible_block_s is not None]
        slacks = [item.slack_to_barrier_s for item in opportunities if item.slack_to_barrier_s is not None]
        positive_saved_by_trace = {path: saved for path, saved in saved_by_trace.items() if saved > 0.0}
        trace_fractions = _trace_saved_fractions(trace_durations, saved_by_trace)
        opportunity_trace_fractions = _positive_trace_saved_fractions(trace_durations, positive_saved_by_trace)
        total_duration = sum(trace_durations.values())
        opportunity_duration = sum(trace_durations.get(path, 0.0) for path in positive_saved_by_trace)
        total_saved = sum(savings)
        summary = ReplaySummary(
            trace_count=trace_count,
            bash_command_count=bash_count,
            pip_install_count=pip_install_count,
            traces_with_pip_install=len(traces_with_pip),
            opportunities_with_barrier=sum(1 for item in opportunities if item.barrier_command is not None),
            opportunities_with_savings=sum(1 for value in savings if value > 0.0),
            total_estimated_saved_s=total_saved,
            median_estimated_saved_s=_median(savings),
            p75_estimated_saved_s=_percentile(savings, 75),
            p90_estimated_saved_s=_percentile(savings, 90),
            median_install_visible_block_s=_median(installs),
            median_slack_to_barrier_s=_median(slacks),
            total_trace_duration_s=total_duration,
            aggregate_saved_fraction=_safe_fraction(total_saved, total_duration),
            opportunity_trace_count=len(positive_saved_by_trace),
            opportunity_trace_duration_s=opportunity_duration,
            opportunity_trace_saved_fraction=_safe_fraction(total_saved, opportunity_duration),
            median_trace_saved_fraction=_median(trace_fractions),
            p75_trace_saved_fraction=_percentile(trace_fractions, 75),
            p90_trace_saved_fraction=_percentile(trace_fractions, 90),
            median_opportunity_trace_saved_fraction=_median(opportunity_trace_fractions),
            p75_opportunity_trace_saved_fraction=_percentile(opportunity_trace_fractions, 75),
            p90_opportunity_trace_saved_fraction=_percentile(opportunity_trace_fractions, 90),
            max_opportunity_trace_saved_fraction=max(opportunity_trace_fractions) if opportunity_trace_fractions else None,
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
            paths = sorted(self.traces.glob("**/*.traj.json"))
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
        visible_block = _visible_block(payload, event)
        barrier = _next_dependency_barrier(bash_events, event_index)
        slack: float | None = None
        saved: float | None = None
        residual: float | None = None
        event_completed_s = event.completed_at_s if event.completed_at_s is not None else event.timestamp_s
        barrier_issued_s = barrier.issued_at_s if barrier is not None else None
        if barrier_issued_s is None and barrier is not None:
            barrier_issued_s = barrier.timestamp_s
        if barrier is not None and event_completed_s is not None and barrier_issued_s is not None:
            slack = max(0.0, barrier_issued_s - event_completed_s)
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
    issued_at_s: float | None
    completed_at_s: float | None
    command: str

    @property
    def timestamp_s(self) -> float | None:
        return self.completed_at_s if self.completed_at_s is not None else self.issued_at_s


def _bash_events(payload: dict[str, Any]) -> Iterable[_BashEvent]:
    if payload.get("trajectory_format") == "mini-swe-agent-1.1":
        yield from _mini_swe_bash_events(payload)
        return
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
                yield _BashEvent(
                    step_index=step_index,
                    issued_at_s=None,
                    completed_at_s=timestamp_s,
                    command=command,
                )


def _mini_swe_bash_events(payload: dict[str, Any]) -> Iterable[_BashEvent]:
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return
    for message_index, message in enumerate(messages):
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        extra = message.get("extra")
        if not isinstance(extra, dict):
            continue
        actions = extra.get("actions")
        if not isinstance(actions, list):
            continue
        issued_at_s = _parse_timestamp(extra.get("timestamp"))
        completed_at_s = _next_mini_swe_observation_timestamp(messages, message_index + 1)
        for action in actions:
            if not isinstance(action, dict):
                continue
            command = action.get("command")
            if isinstance(command, str) and command.strip():
                yield _BashEvent(
                    step_index=message_index,
                    issued_at_s=issued_at_s,
                    completed_at_s=completed_at_s,
                    command=command,
                )


def _next_mini_swe_observation_timestamp(messages: list[object], start: int) -> float | None:
    for message in messages[start:]:
        if not isinstance(message, dict):
            continue
        extra = message.get("extra")
        if not isinstance(extra, dict):
            continue
        if "returncode" in extra or "raw_output" in extra or "exception_info" in extra:
            return _parse_timestamp(extra.get("timestamp"))
        if message.get("role") == "assistant":
            return None
    return None


def _visible_block(payload: dict[str, Any], event: _BashEvent) -> float | None:
    if event.issued_at_s is not None and event.completed_at_s is not None:
        return max(0.0, event.completed_at_s - event.issued_at_s)
    if event.timestamp_s is None:
        return None
    steps = payload.get("steps")
    if not isinstance(steps, list):
        return None
    for previous in reversed(steps[:event.step_index]):
        if not isinstance(previous, dict):
            continue
        previous_ts = _parse_timestamp(previous.get("timestamp"))
        if previous_ts is not None:
            return max(0.0, event.timestamp_s - previous_ts)
    return None


def _next_dependency_barrier(events: list[_BashEvent], install_index: int) -> _BashEvent | None:
    install_event = events[install_index]
    if trace_command_has_python_barrier_after_pip(install_event.command):
        return install_event
    for event in events[install_index + 1:]:
        if trace_command_is_python_barrier(event.command):
            return event
    return None


def _parse_timestamp(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(raw).timestamp()
    except ValueError:
        return None


def _trace_id(trace_path: Path, payload: dict[str, Any]) -> str:
    instance_id = payload.get("instance_id")
    if isinstance(instance_id, str) and instance_id:
        return instance_id
    session = payload.get("session_id")
    if isinstance(session, str) and session:
        return session
    return trace_path.name.removesuffix("-traj.json")


def _trace_duration_s(payload: dict[str, Any]) -> float | None:
    timestamps: list[float] = []
    for value in _iter_payload_timestamps(payload):
        parsed = _parse_timestamp(value)
        if parsed is not None:
            timestamps.append(parsed)
    if len(timestamps) < 2:
        return None
    return max(0.0, max(timestamps) - min(timestamps))


def _iter_payload_timestamps(payload: dict[str, Any]) -> Iterable[object]:
    steps = payload.get("steps")
    if isinstance(steps, list):
        for step in steps:
            if isinstance(step, dict):
                yield step.get("timestamp")
    messages = payload.get("messages")
    if isinstance(messages, list):
        for message in messages:
            if not isinstance(message, dict):
                continue
            extra = message.get("extra")
            if isinstance(extra, dict):
                yield extra.get("timestamp")


def _trace_saved_fractions(
    trace_durations: dict[str, float],
    saved_by_trace: dict[str, float],
) -> list[float]:
    fractions: list[float] = []
    for path, duration in trace_durations.items():
        if duration <= 0.0:
            continue
        fractions.append(saved_by_trace.get(path, 0.0) / duration)
    return fractions


def _positive_trace_saved_fractions(
    trace_durations: dict[str, float],
    saved_by_trace: dict[str, float],
) -> list[float]:
    fractions: list[float] = []
    for path, saved in saved_by_trace.items():
        duration = trace_durations.get(path)
        if duration is None or duration <= 0.0:
            continue
        fractions.append(saved / duration)
    return fractions


def _safe_fraction(numerator: float, denominator: float) -> float | None:
    if denominator <= 0.0:
        return None
    return numerator / denominator


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
