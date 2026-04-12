# Virtual Sandbox Prototype

This repository contains a small prototype for Deferred-Readiness Sandboxes. It is intentionally stdlib-only and self-contained so it can run in a blank research workspace.

The prototype has two parts:

- A live process/venv backend that logically commits pip installs immediately, realizes them asynchronously, and blocks at Python execution barriers.
- A trace replay analyzer for Claude Code ATIF trajectories that estimates how much eager pip-install blocking could be hidden by deferred realization.

This is not a security sandbox. The first backend is a local process backend because Docker is present on this machine but the current sandbox cannot access `/var/run/docker.sock`. A container backend can be added later behind the same runtime API.

## Quick Start

Run the deterministic demo:

```bash
python3 -m vsandbox demo
```

Run the unit tests:

```bash
python3 -m unittest discover -s tests
```

Analyze the provided Terminal-Bench trace corpus:

```bash
python3 -m vsandbox replay \
  --traces /root/workspace/agent-cr/results/traces/tbench-claude-code-claude-opus4.6-trajectories \
  --json
```

Run one command in a fresh sandbox:

```bash
python3 -m vsandbox run --workspace /tmp/vsandbox-work -- python -c "print('hello')"
```

## Runtime Semantics

`VirtualSandbox.run()` classifies each command:

- Pure `pip install`, `pip3 install`, or `python -m pip install` commands are submitted to the realization graph and return immediately as logical commits.
- Python and test commands are execution barriers. The runtime extracts simple imports from `python -c`, `python script.py`, and `python -m module` and waits only for matching pending pip jobs when possible.
- If imports cannot be resolved, the runtime waits for all pending pip jobs before execution.
- Unknown shell commands are conservative barriers: dirty logical file writes are flushed and pending realization jobs are joined before the command runs.
- Logical file reads and writes use an overlay. `read_file()` observes overlay writes immediately, and execution barriers flush dirty overlay files before launching a process.

Late pip failures are reported at the next dependent barrier with the failed job id, command, elapsed time, and stderr.

## Public API

```python
from vsandbox import VirtualSandbox

sandbox = VirtualSandbox.create(workspace="/tmp/work")
result = sandbox.run("python -m pip install requests")
print(result.logically_committed)

result = sandbox.run("python -c \"import requests; print(requests.__version__)\"")
print(result.stdout)
sandbox.shutdown()
```

## Trace Replay Output

The replay analyzer emits an aggregate summary and per-install opportunities. It estimates:

- eager install block time from adjacent ATIF timestamps
- slack from install completion to the next Python/test barrier
- hideable time as `min(eager_block, slack)`
- residual barrier stall as `max(0, eager_block - slack)`

These are analytical estimates, not ground truth timings. They are useful for ranking workloads and validating whether deferred readiness is worth prototyping further.

