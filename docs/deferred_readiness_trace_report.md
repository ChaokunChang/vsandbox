# Deferred-Readiness Trace Replay Report

This report estimates how much end-to-end time the current Deferred-Readiness Sandbox MVP can save on the Claude Code Terminal-Bench trajectory corpus.

## Corpus

- Trace root: `/root/workspace/agent-cr/results/traces/tbench-claude-code-claude-opus4.6-trajectories`
- Trajectory count: 435
- Bash command count: 6,796
- Pip install events detected: 210
- Traces with pip-install deferral opportunities: 92

## Method

The current MVP models only deferred Python package realization. For each detected pip install event:

1. Estimate eager install blocking time from adjacent ATIF step timestamps.
2. Find the next likely Python/test execution barrier.
3. Measure slack from install completion to that barrier.
4. Estimate hideable time as:

```text
estimated_saved = min(eager_install_block, slack_to_barrier)
```

End-to-end time is measured as the first-to-last timestamp duration for each trace.

These values are analytical replay estimates, not live runtime measurements. They do not include possible benefits from lazy base images, apt installs, filesystem materialization, container startup, microVM startup, or prediction.

## Results

Across the full 435-trace corpus:

- Estimated saved time: 903.47 seconds
- Total trace end-to-end time: 200,302.05 seconds
- Fraction of full e2e time saved: 0.45%
- Equivalent aggregate speedup: about 1.0045x

Across only the 92 traces with pip-install deferral opportunities:

- Estimated saved time: 903.47 seconds
- Applicable-trace end-to-end time: 48,338.69 seconds
- Fraction of applicable e2e time saved: 1.87%
- Equivalent aggregate speedup: about 1.019x

Per-trace saved fraction among traces with opportunities:

- Median: 2.02%
- P75: 4.03%
- P90: 8.67%
- Max: 15.56%

## Interpretation

The honest headline for the current MVP scope is:

```text
Deferred pip readiness saves about 0.45% of full-corpus e2e time,
or about 1.9% on applicable pip-heavy traces.
```

The long tail is more encouraging: some individual tasks save 8-15% of e2e time. This supports the research direction, but also shows that pip-only deferral is too narrow to carry the full paper claim by itself. The next prototype target should add broader environment realization classes, especially apt installs and container/base-image readiness.

## Top Individual Trace Fractions

| Saved fraction | Saved time | E2E time | Install events | Trace |
| ---: | ---: | ---: | ---: | --- |
| 15.56% | 33.04s | 212.37s | 4 | `95fc8d64-d83e-42b4-875c-d57dbccd098c-traj.json` |
| 13.84% | 24.64s | 178.03s | 3 | `31884f88-b4f6-4f93-bcb3-dd9339aa265f-traj.json` |
| 13.49% | 25.35s | 187.94s | 4 | `68978396-a4e0-4a99-a332-c397643812da-traj.json` |
| 11.46% | 9.50s | 82.91s | 3 | `eb1b4578-6718-4b33-b01c-97a04ebee3c5-traj.json` |
| 10.31% | 11.91s | 115.59s | 4 | `ed5dd665-9abd-4972-8d17-de7b61fc9ec1-traj.json` |
| 10.30% | 38.51s | 373.80s | 6 | `d84d3f15-e798-460a-8374-62a2defd8084-traj.json` |
| 9.46% | 52.40s | 553.76s | 6 | `c3b88467-7f22-4d03-ac03-5c5c89391db7-traj.json` |
| 9.36% | 9.91s | 105.93s | 3 | `a8b05ec1-1b21-4a70-af9b-a3e865b30368-traj.json` |
| 9.25% | 9.68s | 104.62s | 4 | `1148e612-b376-477c-994d-6263c6d27b96-traj.json` |
| 8.67% | 32.35s | 372.93s | 6 | `62b59602-cfe6-4fc0-b4a4-d69417d176ff-traj.json` |

