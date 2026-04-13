# Deferred-Readiness Trace Replay Report: Claude Code Terminal-Bench

This report estimates how much end-to-end time the current Deferred-Readiness Sandbox MVP can save on the Claude Code Terminal-Bench trajectory corpus.

## Corpus

- Trace root: `/root/workspace/agent-cr/results/traces/tbench-claude-code-claude-opus4.6-trajectories`
- Trajectory count: 435
- Bash command count: 6,796
- Pip install events detected: 210
- Traces with pip-install events: 92

## Method

The current MVP models only deferred Python package realization. For each detected pip install event:

1. Estimate eager install blocking time from trace timestamps.
2. Find the next likely Python/test execution barrier.
3. Measure slack between install completion and that barrier.
4. Estimate hideable time as:

```text
estimated_saved = min(eager_install_block, slack_to_barrier)
```

The analyzer treats commands that install and then run Python in the same shell command, such as `pip install pytest && python -m pytest`, as having zero overlap opportunity. End-to-end time is measured as the first-to-last timestamp duration for each trace.

These values are analytical replay estimates, not live runtime measurements. They do not include possible benefits from lazy base images, apt installs, filesystem materialization, container startup, microVM startup, or prediction.

## Results

Across the full 435-trace corpus:

- Estimated saved time: 809.87 seconds
- Total trace end-to-end time: 200,302.05 seconds
- Fraction of full e2e time saved: 0.40%
- Equivalent aggregate speedup: about 1.0041x

Across traces with positive estimated savings:

- Traces with positive estimated savings: 91
- Estimated saved time: 809.87 seconds
- Applicable-trace end-to-end time: 48,042.67 seconds
- Fraction of applicable e2e time saved: 1.69%
- Equivalent aggregate speedup: about 1.017x

Per-trace saved fraction among traces with positive savings:

- Median: 1.95%
- P75: 4.03%
- P90: 7.40%
- Max: 13.92%

## Interpretation

The current pip-only MVP saves a small fraction of full-corpus end-to-end time:

```text
Deferred pip readiness saves about 0.40% of full-corpus e2e time,
or about 1.7% on Claude Code Terminal-Bench traces with positive pip overlap.
```

The long tail remains useful: several tasks save 7-14% of end-to-end time. This supports the research direction, but also shows that pip-only deferral is too narrow to carry the full paper claim by itself. The next prototype target should add broader environment realization classes, especially apt installs and container/base-image readiness.

## Top Individual Trace Fractions

| Saved fraction | Saved time | E2E time | Positive install events | Trace |
| ---: | ---: | ---: | ---: | --- |
| 13.92% | 29.56s | 212.37s | 3 | `95fc8d64-d83e-42b4-875c-d57dbccd098c-traj.json` |
| 11.66% | 21.90s | 187.94s | 3 | `68978396-a4e0-4a99-a332-c397643812da-traj.json` |
| 11.46% | 9.50s | 82.91s | 3 | `eb1b4578-6718-4b33-b01c-97a04ebee3c5-traj.json` |
| 10.31% | 11.91s | 115.59s | 4 | `ed5dd665-9abd-4972-8d17-de7b61fc9ec1-traj.json` |
| 9.46% | 52.40s | 553.75s | 6 | `c3b88467-7f22-4d03-ac03-5c5c89391db7-traj.json` |
| 9.36% | 9.91s | 105.93s | 3 | `a8b05ec1-1b21-4a70-af9b-a3e865b30368-traj.json` |
| 8.28% | 6.61s | 79.78s | 4 | `58f595ad-c5b0-4862-a903-fce6c3f96b41-traj.json` |
| 8.13% | 6.48s | 79.81s | 2 | `2bd4bd9a-df6e-4ddf-be07-4fab462dd277-traj.json` |
| 7.97% | 7.81s | 98.05s | 3 | `6ca1a3c7-714f-4546-b1c2-d75eb22be493-traj.json` |
| 7.40% | 27.60s | 372.93s | 5 | `62b59602-cfe6-4fc0-b4a4-d69417d176ff-traj.json` |
