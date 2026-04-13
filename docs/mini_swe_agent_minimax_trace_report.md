# Deferred-Readiness Trace Replay Report: Mini-SWE-Agent MiniMax

This report estimates how much end-to-end time the current Deferred-Readiness Sandbox MVP can save on a Mini-SWE-Agent trajectory corpus.

## Corpus

- Trace root: `/root/workspace/agent-cr/results/traces/mini-swe-agent/runs/minimax_verified_test_seed42_n200_resolved_128`
- Trajectory format: `mini-swe-agent-1.1`
- Trajectory count: 128
- Bash command count: 4,836
- Pip install events detected: 292
- Traces with pip-install events: 121

## Method

Mini-SWE-Agent traces store commands in assistant `extra.actions[*].command` entries. The analyzer uses:

- Assistant `extra.timestamp` as command issue time.
- The following user observation `extra.timestamp` as command completion time.
- First-to-last message timestamps as trace end-to-end time.

For each detected pip install event:

1. Estimate eager install blocking time as command completion minus issue time.
2. Find the next likely Python/test execution barrier.
3. Measure slack between install completion and that barrier's issue time.
4. Estimate hideable time as:

```text
estimated_saved = min(eager_install_block, slack_to_barrier)
```

Commands that install and then run Python in the same shell command, such as `pip install pytest && python -m pytest`, are counted as pip events but assigned zero overlap opportunity because the dependent barrier is inside the same command.

These values are analytical replay estimates, not live runtime measurements. They do not include possible benefits from lazy base images, apt installs, filesystem materialization, container startup, microVM startup, or prediction.

## Results

Across the full 128-trace corpus:

- Estimated saved time: 313.16 seconds
- Total trace end-to-end time: 39,386.67 seconds
- Fraction of full e2e time saved: 0.80%
- Equivalent aggregate speedup: about 1.0080x

Across traces with positive estimated savings:

- Traces with positive estimated savings: 66
- Estimated saved time: 313.16 seconds
- Applicable-trace end-to-end time: 22,618.20 seconds
- Fraction of applicable e2e time saved: 1.38%
- Equivalent aggregate speedup: about 1.014x

Per-trace saved fraction among traces with positive savings:

- Median: 1.14%
- P75: 2.07%
- P90: 3.91%
- Max: 16.65%

## Interpretation

The current pip-only MVP saves:

```text
Deferred pip readiness saves about 0.80% of full-corpus e2e time,
or about 1.4% on Mini-SWE-Agent traces with positive pip overlap.
```

Mini-SWE-Agent has many pip commands, but many combine installation and test execution in one shell command. Those commands leave no observable overlap window for the current command-level runtime. The strongest individual trace still saves 16.65%, which suggests meaningful upside for tasks with repeated setup commands and independent work between install and first dependent execution.

## Top Individual Trace Fractions

| Saved fraction | Saved time | E2E time | Positive install events | Trace |
| ---: | ---: | ---: | ---: | --- |
| 16.65% | 67.03s | 402.62s | 8 | `scikit-learn__scikit-learn-14710.traj.json` |
| 7.62% | 8.18s | 107.31s | 3 | `django__django-14493.traj.json` |
| 5.86% | 18.28s | 311.73s | 6 | `scikit-learn__scikit-learn-14894.traj.json` |
| 4.89% | 3.78s | 77.45s | 2 | `pytest-dev__pytest-5631.traj.json` |
| 4.81% | 18.33s | 380.70s | 8 | `scikit-learn__scikit-learn-25232.traj.json` |
| 4.48% | 4.98s | 111.04s | 1 | `django__django-16642.traj.json` |
| 4.13% | 3.17s | 76.58s | 1 | `django__django-12143.traj.json` |
| 3.91% | 5.83s | 149.19s | 2 | `pydata__xarray-4075.traj.json` |
| 3.87% | 8.52s | 220.02s | 5 | `scikit-learn__scikit-learn-10908.traj.json` |
| 3.83% | 6.64s | 173.28s | 4 | `matplotlib__matplotlib-26291.traj.json` |

