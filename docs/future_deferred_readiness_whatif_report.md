# Deferred-Readiness What-If Report: Beyond Pip-Only

This report estimates whether mechanisms beyond the current pip-only Deferred-Readiness MVP are likely to matter before committing to the next implementation phase.

## Scope

Trace corpora analyzed:

- `/root/workspace/agent-cr/results/traces/tbench-claude-code-claude-opus4.6-trajectories`
- `/root/workspace/agent-cr/results/traces/mini-swe-agent/runs/minimax_verified_test_seed42_n200_resolved_128`
- `/root/workspace/agent-cr/results/traces/tbench-terminus-all/submissions/terminal-bench/2.0/*`

The what-if analyzer is available as:

```bash
python3 -m vsandbox whatif --traces <trace-root>
```

## Method

The estimates are independent scenarios. They should not be summed without a more detailed overlap model.

- `pip_baseline`: current command-level pip deferral estimate, matching the previous replay reports.
- `apt_install`: apt-style system dependency commands, deferred until the next likely execution/build/test barrier.
- `git_clone`: `git clone` commands, deferred until the next likely execution/build/test barrier.
- `download`: `curl`, `wget`, Hugging Face CLI, S3, or GCS download commands, deferred until the next likely execution/build/test barrier.
- `base_fs_Ns`: lazy base-image/filesystem readiness where an assumed `N` seconds of readiness work can run during the first model turn before the first terminal command.
- `fine_import_Ns`: incremental savings beyond command-level pip deferral if a Python/test process can start while a dependency is still realizing and only blocks at the actual import/use point after an assumed `N` seconds of pre-import work.

For apt, clone, and download, the "next likely execution/build/test barrier" is deliberately optimistic. A production runtime would need metadata virtualization and path/package provenance to avoid blocking too early on commands such as `cd`, `ls`, or `cat`.

Mini-SWE-Agent traces do not expose an initial task-prompt timestamp in the same way as ATIF traces, so `base_fs_Ns` is zero for that corpus and should be read as undercounted there.

## Aggregate Results

Across all analyzed corpora:

| Mechanism | Events | Positive events | Saved time | Full e2e saved |
| --- | ---: | ---: | ---: | ---: |
| Current pip baseline | 2,174 | 1,306 | 20,431.6s | 0.80% |
| Apt install deferral | 1,795 | 733 | 11,605.8s | 0.45% |
| Git clone deferral | 277 | 130 | 2,221.8s | 0.09% |
| Download deferral | 2,986 | 2,152 | 23,517.9s | 0.92% |
| Base/filesystem readiness, 5s cost | 3,629 | 3,501 | 17,238.6s | 0.67% |
| Base/filesystem readiness, 15s cost | 3,629 | 3,501 | 39,657.1s | 1.55% |
| Base/filesystem readiness, 30s cost | 3,629 | 3,501 | 54,018.0s | 2.11% |
| Base/filesystem readiness, 60s cost | 3,629 | 3,501 | 68,166.7s | 2.66% |
| Fine-grained import, 1s pre-import work | 1,023 | 1,023 | 1,006.7s | 0.04% |
| Fine-grained import, 5s pre-import work | 1,023 | 1,023 | 4,746.3s | 0.19% |
| Fine-grained import, 15s pre-import work | 1,023 | 1,023 | 12,115.6s | 0.47% |

Main takeaways:

- Lazy base/filesystem readiness has the largest broad potential if the true readiness cost is at least 15-30 seconds and can overlap the first model turn.
- Download deferral is the strongest non-pip command capture in these traces. It slightly exceeds the current pip baseline in aggregate, but it is concentrated in specific Terminus collections.
- Apt install deferral is real but smaller than pip or downloads overall. It is strongest in DeepSeek-V3.2.
- Fine-grained in-Python import blocking is incremental and comparatively small unless tests/scripts do substantial work before importing the deferred package.

## Per-Corpus Summary

| Corpus | Pip baseline | Apt | Git clone | Download | Base 15s | Base 30s | Fine import 5s | Fine import 15s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Claude Code Terminal-Bench | 0.40% | 0.08% | 0.01% | 0.14% | 2.10% | 2.91% | 0.04% | 0.10% |
| Mini-SWE-Agent MiniMax | 0.80% | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% | 0.44% | 0.83% |
| Terminus2__Claude-Opus-4.6 | 1.11% | 0.50% | 0.13% | 0.51% | 1.72% | 2.34% | 0.30% | 0.83% |
| Terminus2__DeepSeek-V3.2 | 1.02% | 1.14% | 0.10% | 0.64% | 1.88% | 2.51% | 0.33% | 0.76% |
| Terminus2__GLM-4.7 | 0.89% | 0.39% | 0.10% | 0.65% | 1.17% | 1.54% | 0.19% | 0.49% |
| Terminus2__GLM-5 | 0.89% | 0.36% | 0.09% | 3.01% | 1.60% | 1.99% | 0.15% | 0.39% |
| Terminus2__GPT-5.3-Codex | 0.09% | 0.13% | 0.03% | 0.05% | 2.09% | 3.26% | 0.08% | 0.19% |
| Terminus2__Kimi-k2.5 | 0.63% | 0.39% | 0.14% | 1.38% | 1.35% | 1.69% | 0.21% | 0.53% |
| Terminus2__Minimax-m2.5 | 1.11% | 0.55% | 0.08% | 0.59% | 1.10% | 1.52% | 0.13% | 0.39% |

## Original-Task And Docker Sanity Check

The original Terminal-Bench task definitions under `/root/workspace/agent-cr/results/original-tasks` help interpret the base/filesystem scenario:

- 241 task directories.
- 236 Dockerfiles and 241 docker-compose files.
- Task directories are small: 158.6 MB total, 0.01 MB median, 0.18 MB P90, 80.29 MB max.
- Dockerfiles are mostly based on shared Terminal-Bench images: 99 use `ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624`, and 88 use `ghcr.io/laude-institute/t-bench/python-3-13:20250620`.
- Local Docker inventory includes many prebuilt Terminus and SWE images, ranging from roughly 183 MB to 15.1 GB.

Local Docker calibration on this server:

- Docker: 29.2.1 with `overlayfs`.
- runc: 1.3.4.
- `docker run --rm --network none debian:bookworm-slim true`: 2.93s on first observed run, then 0.28s warm.
- `docker run --rm --network none agent-cr-termnius-bn-fit-modify:latest true`: 0.28s warm.

Interpretation: if task images are already local and warm, container startup alone is too small to justify the 15-60s base/filesystem scenarios. Those scenarios are only plausible for cold image pull/unpack, remote/lazy layer fetch, large prebuilt task images, ZFS snapshot creation, workspace materialization, or other readiness work that currently happens before the agent can issue its first command.

## Recommendation

Priority ranking from the trace evidence:

1. Lazy base-image/filesystem/workspace readiness, if the real cold-readiness path is more than a few seconds. It is broad and can overlap almost every ATIF trace's first model turn. The implementation should first measure actual cold image, snapshot, and workspace setup costs in the production harness.
2. Download realization, including Hugging Face/model/data downloads and `curl`/`wget`. This has the best trace-derived upside among non-startup command captures and reaches 3.01% full-e2e savings in one Terminus2 collection.
3. Apt/system dependency realization. It is smaller than downloads overall but can beat pip in some corpora. It needs stronger dependency semantics because apt packages can affect binaries, shared libraries, headers, services, and Python builds.
4. Fine-grained Python import blocking. This is useful after split-phase pip exists, but the additional trace-level upside is modest: 0.19% aggregate at a 5s pre-import delay and 0.47% at 15s.

The most defensible next step is still to build split-phase package realization as the semantic foundation, but the paper-level speedup story should not rely on pip alone. The next measurement milestone should add cold-readiness benchmarks for image/snapshot/workspace setup and a download-realization prototype, then evaluate those against this what-if report.
