# Deferred-Readiness Trace Replay Report: Terminus2 Terminal-Bench Collections

This report estimates how much end-to-end time the current Deferred-Readiness Sandbox MVP can save on the Terminus2 Terminal-Bench 2.0 trace collections.

## Corpus

- Trace root: `/root/workspace/agent-cr/results/traces/tbench-terminus-all/submissions/terminal-bench/2.0`
- Collections analyzed: 7
- Trace schema: ATIF `ATIF-v1.5` and `ATIF-v1.6` from Terminus2 `agent/trajectory.json` files
- Command format: `tool_calls[*].function_name == "bash_command"` with `arguments.keystrokes` and `arguments.duration`

## Method

The current MVP models only deferred Python package realization. Terminus2 traces store multiple terminal commands in one assistant step, so the analyzer treats each `bash_command` as an ordered shell event:

- `arguments.keystrokes` is normalized into the shell command.
- `arguments.duration` estimates the visible eager blocking time for that command.
- Commands in the same assistant step are placed sequentially using cumulative durations.
- First-to-last trace timestamps, plus synthesized command completion timestamps, define end-to-end trace time.

For each detected pip install event, the replay then finds the next likely Python/test execution barrier and estimates hideable time as:

```text
estimated_saved = min(eager_install_block, slack_to_barrier)
```

Commands that install and then run Python in the same shell command are counted as pip events but assigned zero overlap opportunity. These values are analytical replay estimates, not live runtime measurements. They do not include possible benefits from lazy base images, apt installs, filesystem materialization, container startup, microVM startup, or prediction.

## Summary

| Collection | Traces | Bash commands | Pip installs | Traces with pip | Positive traces | Saved time | Full e2e time | Full e2e saved | Full speedup | Applicable e2e saved | Max trace saved |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `Terminus2__Claude-Opus-4.6` | 445 | 12,274 | 285 | 117 | 78 | 3,083.54s | 277,671.01s | 1.11% | 1.0112x | 4.15% | 25.31% |
| `Terminus2__DeepSeek-V3.2` | 445 | 31,730 | 342 | 135 | 105 | 3,134.64s | 308,787.97s | 1.02% | 1.0103x | 3.55% | 18.35% |
| `Terminus2__GLM-4.7` | 435 | 18,492 | 258 | 99 | 73 | 3,021.79s | 337,903.28s | 0.89% | 1.0090x | 4.37% | 31.89% |
| `Terminus2__GLM-5` | 445 | 18,139 | 220 | 93 | 70 | 3,160.26s | 355,594.25s | 0.89% | 1.0090x | 4.79% | 24.89% |
| `Terminus2__GPT-5.3-Codex` | 445 | 15,814 | 116 | 47 | 23 | 285.83s | 305,680.04s | 0.09% | 1.0009x | 1.24% | 7.28% |
| `Terminus2__Kimi-k2.5` | 442 | 21,787 | 236 | 97 | 67 | 1,966.56s | 312,770.41s | 0.63% | 1.0063x | 4.09% | 19.14% |
| `Terminus2__Minimax-m2.5` | 445 | 16,313 | 215 | 93 | 71 | 4,655.98s | 421,085.08s | 1.11% | 1.0112x | 6.16% | 24.35% |

## Interpretation

Across these collections, the pip-only Deferred-Readiness MVP saves between 0.09% and 1.11% of full-corpus end-to-end time. The strongest full-corpus results are Minimax-m2.5, Claude Opus 4.6, and DeepSeek-V3.2 at roughly 1.1%, while GPT-5.3-Codex is much lower at 0.09% because it has fewer pip-install traces and many immediate barriers.

The applicable-trace view is more informative for the mechanism: when there is positive pip overlap, estimated savings range from about 1.24% to 6.16% of those traces, and individual traces reach 7.28-31.89%. This supports the same conclusion as the earlier reports: pip-only readiness deferral is a real but narrow optimization; broader environment readiness classes are needed for larger aggregate speedups.

## Per-Collection Details

### Terminus2__Claude-Opus-4.6

- Estimated saved time: 3,083.54s
- Total trace end-to-end time: 277,671.01s
- Fraction of full e2e time saved: 1.11%
- Equivalent aggregate speedup: about 1.0112x
- Positive-savings traces: 78
- Fraction of applicable e2e time saved: 4.15%
- Per-positive-trace saved fraction: median 4.48%, P75 9.89%, P90 20.65%, max 25.31%

| Saved fraction | Saved time | E2E time | Positive install events | Trace |
| ---: | ---: | ---: | ---: | --- |
| 25.31% | 25.00s | 98.78s | 2 | `2026-02-05__17-41-47/pypi-server__2CdsxsB/agent/trajectory.json` |
| 24.69% | 25.00s | 101.27s | 2 | `2026-02-05__17-41-47/pypi-server__jc5JVrx/agent/trajectory.json` |
| 24.38% | 90.00s | 369.12s | 2 | `2026-02-05__17-41-47/bn-fit-modify__BVCgTco/agent/trajectory.json` |
| 23.26% | 207.08s | 890.47s | 5 | `2026-02-05__17-41-47/torch-pipeline-parallelism__99R4Kx7/agent/trajectory.json` |
| 23.18% | 178.01s | 768.11s | 5 | `2026-02-05__17-41-47/sam-cell-seg__izqdpzb/agent/trajectory.json` |

### Terminus2__DeepSeek-V3.2

- Estimated saved time: 3,134.64s
- Total trace end-to-end time: 308,787.97s
- Fraction of full e2e time saved: 1.02%
- Equivalent aggregate speedup: about 1.0103x
- Positive-savings traces: 105
- Fraction of applicable e2e time saved: 3.55%
- Per-positive-trace saved fraction: median 2.76%, P75 6.02%, P90 9.08%, max 18.35%

| Saved fraction | Saved time | E2E time | Positive install events | Trace |
| ---: | ---: | ---: | ---: | --- |
| 18.35% | 150.00s | 817.38s | 6 | `2026-02-07__07-47-43/bn-fit-modify__i4BY7Dc/agent/trajectory.json` |
| 17.24% | 153.63s | 891.27s | 4 | `2026-02-07__07-47-43/torch-pipeline-parallelism__LvCufoB/agent/trajectory.json` |
| 13.50% | 44.02s | 326.15s | 2 | `2026-02-07__07-47-43/pytorch-model-cli__yHbwivi/agent/trajectory.json` |
| 12.00% | 160.00s | 1,333.70s | 5 | `2026-02-07__07-47-43/bn-fit-modify__Wss4eHv/agent/trajectory.json` |
| 11.75% | 100.00s | 851.24s | 4 | `2026-02-07__07-47-43/sam-cell-seg__gGQCBja/agent/trajectory.json` |

### Terminus2__GLM-4.7

- Estimated saved time: 3,021.79s
- Total trace end-to-end time: 337,903.28s
- Fraction of full e2e time saved: 0.89%
- Equivalent aggregate speedup: about 1.0090x
- Positive-savings traces: 73
- Fraction of applicable e2e time saved: 4.37%
- Per-positive-trace saved fraction: median 3.65%, P75 7.94%, P90 11.91%, max 31.89%

| Saved fraction | Saved time | E2E time | Positive install events | Trace |
| ---: | ---: | ---: | ---: | --- |
| 31.89% | 180.00s | 564.52s | 4 | `2026-01-27__12-34-00/count-dataset-tokens__XpBaLfW/agent/trajectory.json` |
| 18.58% | 45.00s | 242.20s | 2 | `2026-01-27__12-34-00/sparql-university__q9pqxLN/agent/trajectory.json` |
| 15.18% | 120.00s | 790.58s | 3 | `2026-01-27__12-34-00/torch-pipeline-parallelism__4f4JPJQ/agent/trajectory.json` |
| 14.46% | 108.24s | 748.30s | 4 | `2026-01-27__12-34-00/sam-cell-seg__Mptd5KW/agent/trajectory.json` |
| 14.42% | 47.63s | 330.23s | 2 | `2026-01-27__12-34-00/bn-fit-modify__CbAcBMR/agent/trajectory.json` |

### Terminus2__GLM-5

- Estimated saved time: 3,160.26s
- Total trace end-to-end time: 355,594.25s
- Fraction of full e2e time saved: 0.89%
- Equivalent aggregate speedup: about 1.0090x
- Positive-savings traces: 70
- Fraction of applicable e2e time saved: 4.79%
- Per-positive-trace saved fraction: median 4.24%, P75 8.55%, P90 15.65%, max 24.89%

| Saved fraction | Saved time | E2E time | Positive install events | Trace |
| ---: | ---: | ---: | ---: | --- |
| 24.89% | 120.00s | 482.08s | 3 | `2026-02-14__13-57-51/torch-tensor-parallelism__CRkhJUP/agent/trajectory.json` |
| 21.49% | 187.59s | 873.03s | 4 | `2026-02-14__13-57-51/torch-pipeline-parallelism__G2nscnZ/agent/trajectory.json` |
| 19.05% | 90.00s | 472.37s | 2 | `2026-02-14__13-57-51/bn-fit-modify__Gaeq7F5/agent/trajectory.json` |
| 18.24% | 150.00s | 822.23s | 3 | `2026-02-14__13-57-51/rstan-to-pystan__a8CWLvQ/agent/trajectory.json` |
| 17.52% | 105.00s | 599.16s | 2 | `2026-02-14__13-57-51/bn-fit-modify__5Uo3oWH/agent/trajectory.json` |

### Terminus2__GPT-5.3-Codex

- Estimated saved time: 285.83s
- Total trace end-to-end time: 305,680.04s
- Fraction of full e2e time saved: 0.09%
- Equivalent aggregate speedup: about 1.0009x
- Positive-savings traces: 23
- Fraction of applicable e2e time saved: 1.24%
- Per-positive-trace saved fraction: median 0.59%, P75 1.73%, P90 3.41%, max 7.28%

| Saved fraction | Saved time | E2E time | Positive install events | Trace |
| ---: | ---: | ---: | ---: | --- |
| 7.28% | 35.30s | 485.16s | 5 | `terminus-gpt-5.3-codex-5x/build-cython-ext__iwPmpKr/agent/trajectory.json` |
| 6.01% | 50.10s | 833.42s | 7 | `terminus-gpt-5.3-codex-5x/build-cython-ext__shF9iU9/agent/trajectory.json` |
| 3.41% | 60.00s | 1,757.85s | 1 | `terminus-gpt-5.3-codex-5x/rstan-to-pystan__3jhcQnP/agent/trajectory.json` |
| 2.98% | 5.00s | 167.53s | 1 | `terminus-gpt-5.3-codex-5x/code-from-image__MMXFc3j/agent/trajectory.json` |
| 2.44% | 12.20s | 500.24s | 3 | `terminus-gpt-5.3-codex-5x/build-cython-ext__qg5zCbz/agent/trajectory.json` |

### Terminus2__Kimi-k2.5

- Estimated saved time: 1,966.56s
- Total trace end-to-end time: 312,770.41s
- Fraction of full e2e time saved: 0.63%
- Equivalent aggregate speedup: about 1.0063x
- Positive-savings traces: 67
- Fraction of applicable e2e time saved: 4.09%
- Per-positive-trace saved fraction: median 3.81%, P75 8.00%, P90 12.80%, max 19.14%

| Saved fraction | Saved time | E2E time | Positive install events | Trace |
| ---: | ---: | ---: | ---: | --- |
| 19.14% | 75.00s | 391.78s | 3 | `2026-01-26__22-34-00/bn-fit-modify__s7RQpST/agent/trajectory.json` |
| 18.55% | 56.18s | 302.91s | 5 | `2026-01-26__22-34-00/pypi-server__rRCNcyA/agent/trajectory.json` |
| 16.50% | 71.71s | 434.55s | 2 | `2026-01-26__22-34-00/count-dataset-tokens__wi4nA9b/agent/trajectory.json` |
| 16.17% | 26.00s | 160.83s | 3 | `2026-01-26__22-34-00/pypi-server__kYnP3uX/agent/trajectory.json` |
| 16.02% | 23.02s | 143.70s | 6 | `2026-01-26__22-34-00/pypi-server__M4jdKif/agent/trajectory.json` |

### Terminus2__Minimax-m2.5

- Estimated saved time: 4,655.98s
- Total trace end-to-end time: 421,085.08s
- Fraction of full e2e time saved: 1.11%
- Equivalent aggregate speedup: about 1.0112x
- Positive-savings traces: 71
- Fraction of applicable e2e time saved: 6.16%
- Per-positive-trace saved fraction: median 5.58%, P75 10.79%, P90 13.77%, max 24.35%

| Saved fraction | Saved time | E2E time | Positive install events | Trace |
| ---: | ---: | ---: | ---: | --- |
| 24.35% | 180.00s | 739.16s | 3 | `2026-02-18__13-31-00/bn-fit-modify__QZHRAwF/agent/trajectory.json` |
| 18.17% | 300.00s | 1,650.96s | 5 | `2026-02-18__13-31-00/extract-moves-from-video__SNPe8Ur/agent/trajectory.json` |
| 17.92% | 180.00s | 1,004.52s | 3 | `2026-02-18__13-31-00/rstan-to-pystan__PpUUAtf/agent/trajectory.json` |
| 16.50% | 30.00s | 181.82s | 1 | `2026-02-18__13-31-00/code-from-image__QmvFzst/agent/trajectory.json` |
| 16.31% | 300.00s | 1,839.10s | 5 | `2026-02-18__13-31-00/extract-moves-from-video__895so5P/agent/trajectory.json` |
