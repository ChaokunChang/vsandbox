from __future__ import annotations

import json
import re
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterable

from .barrier import (
    trace_command_has_pip_install,
    trace_command_has_python_barrier_after_pip,
    trace_command_is_python_barrier,
)
from .replay import (
    TraceReplayAnalyzer,
    _BashEvent,
    _bash_events,
    _iter_payload_timestamps,
    _parse_timestamp,
    _trace_duration_s,
    _visible_block,
)


_TRACE_APT_INSTALL_RE = re.compile(
    r"(?:^|[;&|\s])(?:sudo\s+)?(?:apt-get|apt|aptitude)\s+"
    r"(?:install|upgrade|dist-upgrade|build-dep)\b",
    re.IGNORECASE,
)

_TRACE_GIT_CLONE_RE = re.compile(r"(?:^|[;&|\s])git\s+clone\b", re.IGNORECASE)

_TRACE_DOWNLOAD_RE = re.compile(
    r"(?:^|[;&|\s])(?:curl|wget)\b.*(?:https?://|ftp://)|"
    r"\b(?:huggingface-cli|hf)\s+download\b|"
    r"\b(?:aws\s+s3\s+cp|gsutil\s+cp)\b",
    re.IGNORECASE,
)

_TRACE_GENERAL_EXECUTION_RE = re.compile(
    r"(?:^|[;&|\s])(?:python(?:3(?:\.\d+)?)?|pytest|py\.test|ipython|jupyter|streamlit|"
    r"tox|nox|coverage\s+run|make|cmake|gcc|g\+\+|clang|clang\+\+|R|Rscript|node|npm|"
    r"yarn|pnpm|cargo|go|javac|java|mvn|gradle|ruby|bundle|php|composer|bash|sh)\b|"
    r"(?:^|[;&|\s])\./",
    re.IGNORECASE,
)

BASE_READINESS_COSTS_S = (5.0, 15.0, 30.0, 60.0)
FINE_IMPORT_DELAYS_S = (1.0, 5.0, 15.0)


@dataclass(frozen=True)
class MechanismEstimate:
    name: str
    event_count: int
    positive_event_count: int
    positive_trace_count: int
    total_estimated_saved_s: float
    total_trace_duration_s: float
    aggregate_saved_fraction: float | None
    median_event_saved_s: float | None
    p75_event_saved_s: float | None
    p90_event_saved_s: float | None
    median_positive_trace_saved_fraction: float | None
    p75_positive_trace_saved_fraction: float | None
    p90_positive_trace_saved_fraction: float | None
    max_positive_trace_saved_fraction: float | None


@dataclass(frozen=True)
class FutureBenefitSummary:
    trace_count: int
    bash_command_count: int
    total_trace_duration_s: float
    mechanisms: tuple[MechanismEstimate, ...]


class FutureBenefitAnalyzer:
    """Trace-derived what-if estimates for additional deferred-readiness mechanisms."""

    def __init__(self, traces: str | Path, *, limit: int | None = None) -> None:
        self.traces = Path(traces)
        self.limit = limit

    def analyze(self) -> FutureBenefitSummary:
        trace_count = 0
        bash_count = 0
        trace_durations: dict[str, float] = {}
        event_savings: dict[str, list[float]] = {}
        saved_by_trace: dict[str, dict[str, float]] = {}
        event_counts: dict[str, int] = {}

        for trace_path in TraceReplayAnalyzer(self.traces, limit=self.limit)._iter_trace_paths():
            try:
                payload = json.loads(trace_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            trace_count += 1
            trace_key = str(trace_path)
            events = list(_bash_events(payload))
            bash_count += len(events)
            duration = _trace_duration_s(payload, events)
            if duration is not None:
                trace_durations[trace_key] = duration

            for name, savings in _trace_mechanism_savings(payload, events).items():
                event_savings.setdefault(name, []).extend(savings)
                event_counts[name] = event_counts.get(name, 0) + len(savings)
                total_saved = sum(savings)
                if total_saved > 0.0:
                    saved_by_trace.setdefault(name, {})[trace_key] = total_saved

        total_duration = sum(trace_durations.values())
        names = sorted(set(event_counts) | set(event_savings))
        mechanisms = tuple(
            _mechanism_estimate(
                name=name,
                event_count=event_counts.get(name, 0),
                savings=event_savings.get(name, []),
                trace_durations=trace_durations,
                saved_by_trace=saved_by_trace.get(name, {}),
                total_duration=total_duration,
            )
            for name in names
        )
        return FutureBenefitSummary(
            trace_count=trace_count,
            bash_command_count=bash_count,
            total_trace_duration_s=total_duration,
            mechanisms=mechanisms,
        )


def _trace_mechanism_savings(payload: dict[str, object], events: list[_BashEvent]) -> dict[str, list[float]]:
    savings: dict[str, list[float]] = {
        "pip_baseline": _pip_baseline_savings(payload, events),
        "apt_install": _source_overlap_savings(payload, events, _TRACE_APT_INSTALL_RE),
        "git_clone": _source_overlap_savings(payload, events, _TRACE_GIT_CLONE_RE),
        "download": _source_overlap_savings(payload, events, _TRACE_DOWNLOAD_RE),
    }

    first_slack = _first_command_slack_s(payload, events)
    for cost_s in BASE_READINESS_COSTS_S:
        name = f"base_fs_{int(cost_s)}s"
        savings[name] = [min(cost_s, first_slack)] if first_slack is not None else []

    for delay_s in FINE_IMPORT_DELAYS_S:
        name = f"fine_import_{int(delay_s)}s"
        savings[name] = _fine_import_incremental_savings(payload, events, delay_s)

    spec_pip = _speculative_source_savings(payload, events, trace_command_has_pip_install)
    spec_apt = _speculative_source_savings(payload, events, _regex_matcher(_TRACE_APT_INSTALL_RE))
    spec_git = _speculative_source_savings(payload, events, _regex_matcher(_TRACE_GIT_CLONE_RE))
    spec_download = _speculative_source_savings(payload, events, _regex_matcher(_TRACE_DOWNLOAD_RE))
    savings["spec_pip_oracle"] = spec_pip
    savings["spec_apt_oracle"] = spec_apt
    savings["spec_git_clone_oracle"] = spec_git
    savings["spec_download_oracle"] = spec_download
    savings["spec_all_oracle"] = spec_pip + spec_apt + spec_git + spec_download

    return savings


def _pip_baseline_savings(payload: dict[str, object], events: list[_BashEvent]) -> list[float]:
    savings: list[float] = []
    for event_index, event in enumerate(events):
        if not trace_command_has_pip_install(event.command):
            continue
        visible_block = _visible_block(payload, event)
        barrier_index = _next_python_dependency_barrier_index(events, event_index)
        if visible_block is None or barrier_index is None:
            savings.append(0.0)
            continue
        event_completed_s = _event_completed_s(event)
        barrier_issued_s = _event_issued_s(events[barrier_index])
        if event_completed_s is None or barrier_issued_s is None:
            savings.append(0.0)
            continue
        slack = max(0.0, barrier_issued_s - event_completed_s)
        savings.append(min(visible_block, slack))
    return savings


def _source_overlap_savings(
    payload: dict[str, object],
    events: list[_BashEvent],
    source_re: re.Pattern[str],
) -> list[float]:
    savings: list[float] = []
    for event_index, event in enumerate(events):
        if not source_re.search(event.command):
            continue
        visible_block = _visible_block(payload, event)
        barrier_index = _next_general_execution_barrier_index(events, event_index, source_re)
        if visible_block is None or barrier_index is None:
            savings.append(0.0)
            continue
        event_completed_s = _event_completed_s(event)
        barrier_issued_s = _event_issued_s(events[barrier_index])
        if event_completed_s is None or barrier_issued_s is None:
            savings.append(0.0)
            continue
        slack = max(0.0, barrier_issued_s - event_completed_s)
        savings.append(min(visible_block, slack))
    return savings


def _fine_import_incremental_savings(
    payload: dict[str, object],
    events: list[_BashEvent],
    assumed_pre_import_delay_s: float,
) -> list[float]:
    savings: list[float] = []
    for event_index, event in enumerate(events):
        if not trace_command_has_pip_install(event.command):
            continue
        barrier_index = _next_python_dependency_barrier_index(events, event_index)
        if barrier_index is None or barrier_index == event_index:
            continue
        barrier = events[barrier_index]
        if not trace_command_is_python_barrier(barrier.command):
            continue
        visible_block = _visible_block(payload, event)
        event_completed_s = _event_completed_s(event)
        barrier_issued_s = _event_issued_s(barrier)
        if visible_block is None or event_completed_s is None or barrier_issued_s is None:
            continue
        slack = max(0.0, barrier_issued_s - event_completed_s)
        residual_stall = max(0.0, visible_block - slack)
        if residual_stall > 0.0:
            savings.append(min(residual_stall, assumed_pre_import_delay_s))
    return savings


def _speculative_source_savings(
    payload: dict[str, object],
    events: list[_BashEvent],
    source_matches: Callable[[str], bool],
) -> list[float]:
    trace_start_s = _trace_start_s(payload, events)
    savings: list[float] = []
    for event in events:
        if not source_matches(event.command):
            continue
        visible_block = _visible_block(payload, event)
        issue_s = _event_issue_estimate_s(payload, event)
        if trace_start_s is None or visible_block is None or issue_s is None:
            savings.append(0.0)
            continue
        pre_issue_slack_s = max(0.0, issue_s - trace_start_s)
        savings.append(min(visible_block, pre_issue_slack_s))
    return savings


def _next_python_dependency_barrier_index(events: list[_BashEvent], install_index: int) -> int | None:
    install_event = events[install_index]
    if trace_command_has_python_barrier_after_pip(install_event.command):
        return install_index
    for event_index, event in enumerate(events[install_index + 1 :], start=install_index + 1):
        if trace_command_is_python_barrier(event.command):
            return event_index
    return None


def _next_general_execution_barrier_index(
    events: list[_BashEvent],
    source_index: int,
    source_re: re.Pattern[str],
) -> int | None:
    source_event = events[source_index]
    source_match = source_re.search(source_event.command)
    if source_match is not None and _TRACE_GENERAL_EXECUTION_RE.search(source_event.command[source_match.end() :]):
        return source_index
    for event_index, event in enumerate(events[source_index + 1 :], start=source_index + 1):
        if _TRACE_GENERAL_EXECUTION_RE.search(event.command):
            return event_index
    return None


def _first_command_slack_s(payload: dict[str, object], events: list[_BashEvent]) -> float | None:
    if not events:
        return None
    start = _trace_start_s(payload, events)
    command_starts = [value for value in (_event_issued_s(event) for event in events) if value is not None]
    if start is None or not command_starts:
        return None
    return max(0.0, min(command_starts) - start)


def _trace_start_s(payload: dict[str, object], events: Iterable[_BashEvent]) -> float | None:
    timestamps: list[float] = []
    for value in _iter_payload_timestamps(payload):
        parsed = _parse_timestamp(value)
        if parsed is not None:
            timestamps.append(parsed)
    for event in events:
        issued_at_s = _event_issued_s(event)
        completed_at_s = _event_completed_s(event)
        if issued_at_s is not None:
            timestamps.append(issued_at_s)
        if completed_at_s is not None:
            timestamps.append(completed_at_s)
    return min(timestamps) if timestamps else None


def _event_issued_s(event: _BashEvent) -> float | None:
    return event.issued_at_s if event.issued_at_s is not None else event.timestamp_s


def _event_issue_estimate_s(payload: dict[str, object], event: _BashEvent) -> float | None:
    if event.issued_at_s is not None:
        return event.issued_at_s
    completed_at_s = _event_completed_s(event)
    visible_block = _visible_block(payload, event)
    if completed_at_s is not None and visible_block is not None:
        return completed_at_s - visible_block
    return event.timestamp_s


def _event_completed_s(event: _BashEvent) -> float | None:
    return event.completed_at_s if event.completed_at_s is not None else event.timestamp_s


def _regex_matcher(pattern: re.Pattern[str]) -> Callable[[str], bool]:
    return lambda command: bool(pattern.search(command))


def _mechanism_estimate(
    *,
    name: str,
    event_count: int,
    savings: list[float],
    trace_durations: dict[str, float],
    saved_by_trace: dict[str, float],
    total_duration: float,
) -> MechanismEstimate:
    positive_savings = [value for value in savings if value > 0.0]
    trace_fractions = _positive_trace_saved_fractions(trace_durations, saved_by_trace)
    total_saved = sum(savings)
    return MechanismEstimate(
        name=name,
        event_count=event_count,
        positive_event_count=len(positive_savings),
        positive_trace_count=len(saved_by_trace),
        total_estimated_saved_s=total_saved,
        total_trace_duration_s=total_duration,
        aggregate_saved_fraction=_safe_fraction(total_saved, total_duration),
        median_event_saved_s=_median(positive_savings),
        p75_event_saved_s=_percentile(positive_savings, 75),
        p90_event_saved_s=_percentile(positive_savings, 90),
        median_positive_trace_saved_fraction=_median(trace_fractions),
        p75_positive_trace_saved_fraction=_percentile(trace_fractions, 75),
        p90_positive_trace_saved_fraction=_percentile(trace_fractions, 90),
        max_positive_trace_saved_fraction=max(trace_fractions) if trace_fractions else None,
    )


def _positive_trace_saved_fractions(
    trace_durations: dict[str, float],
    saved_by_trace: dict[str, float],
) -> list[float]:
    fractions: list[float] = []
    for path, saved in saved_by_trace.items():
        duration = trace_durations.get(path)
        if duration is not None and duration > 0.0:
            fractions.append(saved / duration)
    return fractions


def _safe_fraction(numerator: float, denominator: float) -> float | None:
    if denominator <= 0.0:
        return None
    return numerator / denominator


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def _percentile(values: list[float], percentile: int) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = round((len(ordered) - 1) * (percentile / 100.0))
    return ordered[int(index)]


def summary_to_json(summary: FutureBenefitSummary) -> str:
    return json.dumps(asdict(summary), indent=2, sort_keys=True)
