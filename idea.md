Working title

Deferred-Readiness Sandboxes: Temporal Virtualization for Interactive Isolated Execution

A shorter internal name can still be Virtual Sandbox.

1. Problem statement

Modern LLM agents rely on isolated execution environments to run tools, install packages, mutate files, and execute code safely. Today, these environments are usually containers or microVMs, and they are treated as if they must be fully realized before the agent can make progress. In practice, that assumption is too strict.

Agent workloads are interactive and slack-rich. An agent may request a container, install dependencies, edit files, and continue reasoning for many turns before it actually executes the code path that needs those dependencies. Eagerly realizing the entire sandbox up front wastes time in the critical loop, especially when setup is heavy, partially unnecessary, or only needed much later.

The key opportunity is to decouple logical sandbox readiness from physical sandbox realization. The agent should be able to observe and manipulate a sandbox as if it is ready, while the system defers expensive realization work until some later action semantically requires it.

2. Main abstraction

The system exposes a logically ready sandbox backed by a partially materialized execution state.

The sandbox state is split into two layers:

Logical state: the environment as presented to the agent and tool runtime.
Physical state: the actually realized VM/container/image/files/packages/processes needed to execute.

The runtime maintains a dependency graph over environment components:

base image and filesystem layers
VM or process state
package and dependency transactions
file mutations and overlays
capabilities, mounts, and secrets

Operations may complete in one of two modes:

logically committed: visible in the sandbox model
physically realized: fully executable without further blocking

The core contract is:

An operation should block only when the next action causally depends on physical realization.

3. Semantics

This section is what will make the paper feel like systems work instead of just optimization.

3.1 Split-phase environment mutations

Environment-changing actions are split into:

submit: record the requested mutation into the sandbox state
realize: fetch/build/materialize required artifacts
commit barrier: block when some future action truly needs the result

Examples:

apt install ripgrep can return after submit
rg foo . becomes the barrier if ripgrep is not yet usable
creating a file overlay can return immediately
executing a binary from that overlay is the barrier
3.2 Barrier types

You can define three barrier classes.

Observation barrier
A command that only inspects logical metadata may proceed without full realization.

Execution barrier
A command that needs bytes, binaries, imports, pages, or process state must wait until the required parts are realized.

External side-effect barrier
Operations with irreversible external effects cannot be completed speculatively. They require physical readiness before commit.

3.3 Consistency model

A strong but tractable model is:

read-your-logical-writes for metadata and environment declarations
execution consistency at barrier points
no speculative completion of irreversible side effects

This keeps the semantics clean without requiring impossible rollback.

4. System sketch

I would present the system as four components.

4.1 Intent capture layer

Intercept agent/tool actions that mutate the environment:

install package
create/modify file
request runtime
mount dataset
configure secret/capability

Compile them into an environment realization graph.

4.2 Realization engine

Resolve graph nodes asynchronously using different backends:

lazy image loading
snapshot resume
package artifact fetch/build
filesystem overlay population
remote cache lookup

This layer is backend-agnostic. That is important. Your idea should not depend on one container stack.

4.3 Barrier handler

When the agent issues a command that actually needs some unrealized component, the system:

identifies the missing dependency set
prioritizes those nodes
blocks only on the minimal cut needed for correctness

That “minimal cut” phrasing is useful and sounds publishable.

4.4 Predictor/speculator

Optional optimization:

use static hints from the environment graph
use command history
use agent-declared next actions
use import/build heuristics

Keep this as an optimization, not the main contribution.

5. Example execution trace

A concrete trace will help a lot.

Agent requests Python sandbox.
Runtime returns a logically ready sandbox immediately.
Agent issues pip install pandas matplotlib.
Runtime records package transaction and starts realization asynchronously.
Agent spends 8 seconds reading CSV schema and writing analysis code.
Agent edits analyze.py.
Agent runs python analyze.py.
Barrier handler sees imports require pandas and matplotlib.
If realization is complete, execution starts immediately.
If not, execution blocks only until those specific dependencies are usable.

This trace makes the value obvious: setup time is overlapped with reasoning time.

6. What the paper should claim

I would aim for these claims.

Claim 1
Interactive sandboxed workloads spend unnecessary time waiting for eager environment realization.

Claim 2
A deferred-readiness abstraction can preserve correct execution semantics while reducing agent-visible blocking.

Claim 3
The largest gains come from overlap between environment realization and non-dependent reasoning/tool activity, not merely from lower cold-start overhead.

Claim 4
A graph-based sandbox model allows the system to block on only the minimal physically necessary state.

7. Likely contributions

A clean contribution set could be:

Abstraction
Deferred-readiness sandboxes as a new model for isolated interactive execution.
Semantics
A split-phase execution model with explicit barrier semantics.
System
A prototype runtime that virtualizes sandbox readiness over containers/microVMs and dependency realization.
Evaluation
Evidence that this reduces agent-visible blocking and end-to-end task latency on realistic agent traces.
8. What not to claim

Avoid these formulations because they sound incremental:

faster container startup
lazy dependency install
background package installation
another warm pool
better cache for agent sandboxes

Those are implementation consequences, not the paper idea.

9. Research questions

These are the concrete questions I would use to drive the project.

RQ1
How much sandbox setup in agent workloads is not immediately on the critical path?

RQ2
Can sandbox readiness be virtualized with clear correctness semantics?

RQ3
What are the right barrier points that preserve correctness but maximize overlap?

RQ4
How much benefit comes from basic deferred realization alone, versus prediction/speculation?

RQ5
What failure modes appear when logically committed state fails to physically realize later?

10. Evaluation plan

You need one metric that matches the thesis.

Primary metric

Agent-visible blocking time
Total time the agent is stalled waiting for sandbox readiness or dependency realization.

Secondary metrics
end-to-end task latency
time to first useful tool result
realized vs requested dependency volume
speculative waste
cache hit ratio
barrier frequency and stall distribution
correctness mismatches
overhead of maintaining logical state
Workloads

Use trace-driven and live workloads:

code agents with Python/Node installs
data-analysis agents with large libraries
branchy debugging tasks
multi-turn tasks with early setup and late execution
Baselines
eager container/microVM startup
pre-baked image baseline
warm pool baseline
lazy image loading only
snapshot restore only
11. Main risks

These are the hardest parts, and also where the paper becomes interesting.

Semantic leakage
The agent may observe inconsistent state if logical and physical readiness are not carefully separated.

Late failure
A package/build may fail after the agent has already proceeded under the assumption it will succeed.

Side effects
External writes cannot be “virtually done” safely.

Debuggability
When execution blocks, users need to understand what the sandbox is waiting on.

Security/trust
Deferred fetch/build broadens the supply-chain surface.

12. Minimal prototype

Do not try to build the full general system first.

A good MVP is:

one container backend
Python-only dependency transactions
filesystem overlay support
explicit barrier detection for:
binary execution
Python import
file open on missing content

That is enough to validate the core thesis.

A very reasonable prototype path:

Phase 1
Trace and measure idle overlap opportunities in real agent runs.

Phase 2
Build split-phase pip install + barrier-on-import execution.

Phase 3
Add lazy base image/filesystem realization.

Phase 4
Add predictor/speculation.

13. Draft abstract

Here is a first-pass abstract you can refine later.

Interactive AI agents increasingly rely on isolated execution sandboxes to run tools, install dependencies, and manipulate state. Existing sandbox runtimes treat environment readiness as an eager prerequisite: containers, microVM state, and dependencies are typically realized before the agent can proceed. However, agent workloads are interactive and temporally sparse: environment mutations often precede by many seconds the first execution that truly depends on them. We present Deferred-Readiness Sandboxes, a runtime abstraction that decouples logical sandbox readiness from physical realization. Our system allows agents to interact with a logically consistent sandbox while asynchronously materializing images, dependencies, and execution state, blocking only at semantically necessary barrier points. We define split-phase semantics for environment mutations, design a graph-based realization engine, and implement a prototype over existing sandbox backends. Across representative agent workloads, deferred-readiness sandboxes reduce agent-visible blocking and improve end-to-end task latency by overlapping environment setup with independent reasoning and tool activity.

14. Elevator pitch

Here is the sharpest version:

Current sandboxes make agents wait for environment setup too early. We want a sandbox that is logically ready now and physically realized only when execution truly needs it.

15. Best immediate next action

The single best next action is to write a 2-page extended abstract with these section headers:

Motivation
Abstraction
Semantics
Design
Prototype scope
Evaluation plan
Risks and limitations

That document will tell you very quickly whether the idea is real or still too fuzzy.
