# Speculative Readiness Prediction Report

This note documents the planned prediction/speculation optimization for Deferred-Readiness Sandboxes and estimates its trace-level upside.

## Idea

The current MVP waits until the agent explicitly asks for readiness work, such as:

```bash
pip install pandas
apt-get install -y libhdf5-dev
git clone https://github.com/example/project
wget https://example.com/model.bin
```

Even if the runtime makes those operations logically commit quickly, demand-driven realization only starts after the LLM emits the action. That leaves earlier agent thinking and exploration time unused.

Speculative readiness starts likely readiness work before the agent asks for it:

```text
task arrives
-> predictor reads task, repo metadata, manifests, and prior traces
-> predictor starts likely installs/downloads/clones in the background
-> agent loop starts normally
-> when the agent later asks for that dependency, it is already ready or partially ready
```

The goal is different from command-level deferred pip. Deferred pip mostly reduces blocking after the install command. Speculation reduces full end-to-end time by hiding installation/download/clone latency before the install command is ever issued.

## Prediction Inputs

A predictor can be rule-based, model-based, or hybrid.

Useful low-cost signals:

- Task description mentions packages, tools, models, datasets, repositories, or binaries.
- Repository manifests: `pyproject.toml`, `requirements.txt`, `package.json`, `Cargo.toml`, `go.mod`, CI configs.
- Imports and dependency metadata from a lazy repo index.
- Files mentioned in the issue, PR, or user task.
- Historical traces for similar tasks.
- Benchmark metadata such as task category or Dockerfile.

Examples:

- Task says "use Qwen tokenizer" and Hugging Face dataset: speculate `transformers`, `datasets`, `huggingface_hub`, model/tokenizer cache.
- Task says "compile Cython extension": speculate build toolchain, Python headers, `cython`, `numpy`, repository clone.
- Task says "convert RStan to PyStan": speculate `pystan`, compiler toolchain, and relevant data file hydration.
- Repository has `requirements.txt`: start installing likely top-level requirements while the first agent turn runs.

## Runtime Semantics

Speculative readiness should not mutate the visible workspace until committed by demand or a safe policy.

Recommended semantics:

1. Start speculative jobs in isolated realization slots.
2. Record provenance: predicted package/version/source, task id, predictor, and confidence.
3. If the agent later issues a matching command, attach the speculative job and return immediately if complete.
4. If the job is incomplete, wait only for the residual.
5. If prediction was wrong, discard or cache the artifact without exposing side effects.
6. If two predictions conflict, keep them isolated until the agent chooses one.

For pip, this maps cleanly to split-phase package realization. For apt and downloads, stronger provenance and path/package barriers are needed because side effects are broader.

## Estimate Model

The estimator added to `python3 -m vsandbox whatif` reports these oracle speculation mechanisms:

- `spec_pip_oracle`
- `spec_apt_oracle`
- `spec_git_clone_oracle`
- `spec_download_oracle`
- `spec_all_oracle`

For each observed readiness command, the oracle assumes:

- the predictor knows the exact future command,
- realization starts at trace start,
- speculative jobs can run in parallel without resource contention,
- false positives have no cost,
- the observed command block is the maximum hideable readiness latency.

For an event:

```text
speculative_saved = min(observed_command_block, command_issue_time - trace_start_time)
```

This is an upper bound. It can overestimate commands that combine install and execution in one shell line because the trace may not separate install time from subsequent work. It can also underestimate corpora that do not record the user-task timestamp before the first agent action.

## Aggregate Results

Across all analyzed corpora:

| Mechanism | Events | Positive events | Positive traces | Saved time | Full e2e saved |
| --- | ---: | ---: | ---: | ---: | ---: |
| Current pip baseline | 2,174 | 1,306 | 644 | 20,431.6s | 0.80% |
| Speculative pip oracle | 2,174 | 2,174 | 894 | 49,728.1s | 1.94% |
| Speculative apt oracle | 1,795 | 1,795 | 1,061 | 42,635.7s | 1.67% |
| Speculative git-clone oracle | 277 | 277 | 199 | 3,692.7s | 0.14% |
| Speculative download oracle | 2,986 | 2,986 | 437 | 28,952.2s | 1.13% |
| Speculative all-readiness oracle | 7,232 | 7,232 | 1,668 | 125,008.7s | 4.88% |

The all-readiness oracle is much larger than the current pip baseline because it hides latency before the agent emits the install/download/clone command, including cases where the install is immediately followed by a dependent command.

If real prediction captures only a fraction of the oracle opportunity, the approximate full-e2e savings are:

| Effective oracle hit rate | Saved time | Full e2e saved |
| ---: | ---: | ---: |
| 25% | 31,252.2s | 1.22% |
| 50% | 62,504.4s | 2.44% |
| 75% | 93,756.5s | 3.66% |
| 100% | 125,008.7s | 4.88% |

This linear hit-rate table ignores false-positive resource contention. It is best read as a sensitivity analysis, not a guarantee.

## Per-Corpus Results

| Corpus | Current pip | Spec pip | Spec apt | Spec git | Spec download | Spec all |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Claude Code Terminal-Bench | 0.40% | 0.54% | 0.24% | 0.04% | 0.27% | 1.08% |
| Mini-SWE-Agent MiniMax | 0.80% | 4.18% | 0.00% | 0.00% | 0.00% | 4.18% |
| Terminus2__Claude-Opus-4.6 | 1.11% | 3.09% | 1.67% | 0.18% | 0.67% | 5.61% |
| Terminus2__DeepSeek-V3.2 | 1.02% | 2.37% | 3.47% | 0.20% | 0.84% | 6.87% |
| Terminus2__GLM-4.7 | 0.89% | 2.13% | 1.59% | 0.18% | 0.83% | 4.74% |
| Terminus2__GLM-5 | 0.89% | 1.79% | 1.14% | 0.11% | 3.30% | 6.35% |
| Terminus2__GPT-5.3-Codex | 0.09% | 0.52% | 1.11% | 0.07% | 0.08% | 1.78% |
| Terminus2__Kimi-k2.5 | 0.63% | 1.86% | 1.77% | 0.21% | 1.82% | 5.65% |
| Terminus2__Minimax-m2.5 | 1.11% | 2.41% | 2.00% | 0.15% | 0.83% | 5.38% |

## Interpretation

Speculation is one of the better full-e2e optimizations in the current trace set:

- Current demand-driven pip baseline: 0.80% aggregate full-e2e savings.
- Speculative pip alone: 1.94%.
- Speculative all-readiness oracle: 4.88%.
- A 50% effective hit rate on all-readiness speculation still gives about 2.44%, larger than the current pip baseline and comparable to or larger than the base/filesystem 30s scenario in the what-if report.

The highest-value prediction targets are not only Python packages:

- Apt speculation is large in Terminus2__DeepSeek-V3.2 and several other Terminus collections.
- Download speculation is large in Terminus2__GLM-5 and Terminus2__Kimi-k2.5.
- Git clone speculation is smaller in these traces, but it remains strategically important for remote coding agents because full repository clone and checkout latency is mostly absent from these already-running benchmark traces.

## Design Risks

Speculation can hurt if it is not controlled:

- False positives consume CPU, disk, network, and package-cache bandwidth.
- Wrong apt operations can mutate global system state if not isolated.
- Version conflicts can poison caches or make later commands less reproducible.
- Network-heavy speculation can interfere with the agent's actual command.
- The predictor may leak benchmark/task information into artifacts if provenance is not tracked.

Mitigations:

- Use isolated realization sandboxes and content-addressed caches.
- Commit speculative artifacts only on exact command match or high-confidence semantic match.
- Rate-limit speculation and prioritize high-confidence, low-cost jobs.
- Prefer metadata-only or cache-warming speculation before heavyweight installs.
- Track predictor decisions in logs for replay and ablation.

## Recommendation

Add speculation after the runtime has split-phase realization semantics for at least pip and downloads. A practical first version:

1. Rule predictor from task text and repository manifests.
2. Speculate pip packages, Hugging Face/model downloads, and explicit repository URLs.
3. Run speculative jobs in isolated realization slots.
4. Attach jobs on exact command match.
5. Measure full e2e and TTFT/TTFC/TTFR separately.

For the research story, speculation is important because it changes the optimization target from "hide latency after demand" to "start readiness before demand." That is the mechanism most likely to reduce full e2e time rather than only improving responsiveness at a dependency barrier.
