# Deferred-Readiness For Remote Coding Agents

Remote coding agents are the strongest product setting for Deferred-Readiness Sandboxes. In systems like Codex remote execution, Google Jules, or similar cloud agents, the user submits a task and then waits while the platform provisions a VM/container, prepares the image, clones the repository, checks out files, initializes the workspace, and only then starts the agent loop.

The current pip-only MVP mostly measures end-to-end savings after the agent is already running. That is useful, but it undersells the broader idea. For remote agents, the more important latency target is time-to-first-useful-work: the agent should be able to start reasoning, inspect repository metadata, and read the first few relevant files before the entire environment and repository are fully materialized.

## Serialized Baseline

A conventional remote-agent startup path looks like:

```text
user submits task
-> allocate VM/container
-> pull/unpack/prepare image
-> create filesystem/snapshot/workspace
-> clone repository
-> checkout all files
-> install or mount caches
-> start agent loop
-> first assistant token
-> first terminal command
-> first repository file read
```

This path is conservative but expensive: the agent is blocked on resources it may not use for several turns, or may never use at all.

## Deferred-Readiness Path

Deferred readiness makes the environment observable before it is fully realized:

```text
user submits task
-> start first agent turn with task text and repository metadata
-> concurrently provision VM/container
-> concurrently expose lazy filesystem and lazy Git tree
-> concurrently hydrate likely first-use files
-> block only when the agent touches an unrealized object
```

The key shift is from:

```text
ready means everything is present
```

to:

```text
ready means the next operation has the objects it needs
```

This is a better match for agent behavior. The agent usually starts by reading task text, listing files, opening README/config files, grepping a narrow symbol, or inspecting a few tests. It rarely needs every blob in the repository, every image layer, and every dependency before the first useful action.

## Metrics

For this use case, full end-to-end time is only one metric. The more sensitive metrics are:

- `TTFT`: task submission to first visible assistant token.
- `TTFC`: task submission to first terminal command start.
- `TTFR`: task submission to first repository file read success.
- `TTFU`: task submission to first useful repo-dependent action completion.
- `E2E`: task submission to final answer or passing tests.

The expected win is largest for `TTFT`, `TTFC`, `TTFR`, and `TTFU`. E2E speedup may remain modest if later test/build time dominates, but the user-visible latency improvement can still be large.

## Lazy Repository Semantics

A remote coding agent does not need a full `git clone` before it can begin. A lazy Git workspace can expose:

- Commit identity and branch metadata.
- Directory tree metadata.
- File paths, modes, sizes, and object IDs.
- High-value small files such as `README`, `pyproject.toml`, `package.json`, lockfiles, CI configs, and test manifests.
- A working tree interface that hydrates file blobs on first read.

Operation semantics:

| Operation | Required readiness |
| --- | --- |
| `pwd` | workspace mount only |
| `ls` / directory walk | tree metadata for the listed directory |
| `cat path` / editor open | the requested blob |
| targeted `rg pattern path` | blobs under the requested path, or a remote search index |
| full-repo `rg pattern .` | broad blob hydration or remote index |
| `git status` | tree metadata plus dirty overlay state |
| `python`, `pytest`, `npm test`, build commands | stronger barrier, often requiring many source files and dependencies |

The runtime should return normal filesystem behavior whenever possible. If an operation touches unrealized content, it blocks at that point, hydrates the needed object, and then continues.

## Lazy Image And Filesystem Semantics

The same idea applies below the repository:

- Container image layers can be fetched and mounted lazily.
- Snapshot/workspace creation can happen in the background.
- Large task assets can hydrate on first path access.
- Dependency caches can appear as logical mounts before every file is locally present.

Warm container startup on the current server is only about 0.28s in the measured Docker sanity check, so warm startup alone is not enough to drive the 15-60s base-readiness scenarios in the what-if report. The opportunity is in cold image pull/unpack, lazy remote layer fetch, large prebuilt task images, workspace copy/snapshot cost, task asset hydration, and repository clone/materialization.

## Prefetch Policy

Deferred readiness should not be purely reactive. The system can start from a cheap, high-confidence prefetch set:

- top-level README and task instructions
- package/build manifests
- test configuration files
- language-specific entry points
- files mentioned in the user request
- files mentioned in issue/PR metadata
- recently changed files for PR-style tasks

After the first model response begins, prefetch can follow the agent's plan:

- If the model says it will inspect tests, hydrate likely test directories.
- If it names a package/module, hydrate that subtree.
- If it plans to run a build, hydrate build inputs and dependency metadata.

This creates an overlap window during the first model turn and reduces the probability of blocking at first file access.

## Relation To Existing Reports

The current trace reports are conservative for this scenario because the traces generally begin after the benchmark environment is already available. They do not fully capture:

- cloud VM allocation latency
- cold image pull and unpack latency
- container snapshot setup
- full repository clone latency
- checkout of large histories or large worktrees
- platform-side workspace copy
- initial indexing

The what-if report still shows that lazy base/filesystem readiness can dominate pip-only savings if there is 15-30s of readiness work to hide. Remote coding agents are exactly the deployment model where that hidden work is likely to exist.

## Prototype Direction

The next prototype should treat split-phase pip as one semantic instance of a broader access-barrier model, not as the whole project.

Recommended phases:

1. Lazy Git workspace.
   - Build an immediate virtual worktree from Git tree metadata.
   - Hydrate blobs on file read.
   - Maintain a writable overlay for agent edits.
   - Support basic `ls`, `cat`, `git status`, targeted search, and editor-style reads.

2. Startup overlap harness.
   - Measure task submission to first model call, first command, and first file read.
   - Include cold VM/container/image/workspace/repo setup.
   - Compare eager clone/checkout against lazy tree plus blob-on-read.

3. Lazy image/filesystem readiness.
   - Use lazy layer mounting, lazy snapshot hydration, or a user-space filesystem shim.
   - Treat file access as the readiness barrier.
   - Prefetch likely first-use paths during the first model turn.

4. Split-phase dependency realization.
   - Pip packages, apt packages, downloads, and model/data assets become background realization jobs.
   - Python imports, binary execution, shared-library loads, header access, and path reads become dependency-specific barriers.

## Research Claim

The stronger claim is:

```text
Remote coding agents should not wait for the entire environment and repository
before starting. They only need a truthful interface that blocks at first actual
use of missing objects.
```

This reframes Deferred-Readiness Sandboxes as a latency-hiding substrate for remote agents. Pip-only deferral is a useful mechanism, but lazy repository, filesystem, and environment realization are the larger product opportunity because they reduce time-to-first-useful-work, not just final task runtime.
