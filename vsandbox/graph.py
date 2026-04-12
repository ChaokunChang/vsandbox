from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class JobResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


@dataclass
class RealizationNode:
    id: str
    kind: str
    command: str
    packages: tuple[str, ...] = ()
    package_imports: tuple[str, ...] = ()
    state: str = "queued"
    submitted_at: float = field(default_factory=time.monotonic)
    started_at: float | None = None
    finished_at: float | None = None
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""
    error: str | None = None
    event: threading.Event = field(default_factory=threading.Event, repr=False)
    thread: threading.Thread | None = field(default=None, repr=False)

    @property
    def elapsed_s(self) -> float:
        end = self.finished_at if self.finished_at is not None else time.monotonic()
        return max(0.0, end - self.submitted_at)

    @property
    def is_finished(self) -> bool:
        return self.state in {"succeeded", "failed"}

    def snapshot(self) -> dict[str, object]:
        return {
            "id": self.id,
            "kind": self.kind,
            "command": self.command,
            "packages": list(self.packages),
            "package_imports": list(self.package_imports),
            "state": self.state,
            "elapsed_s": self.elapsed_s,
            "returncode": self.returncode,
            "error": self.error,
        }


class RealizationGraph:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._nodes: dict[str, RealizationNode] = {}
        self._next_id = 1

    def submit(
        self,
        *,
        kind: str,
        command: str,
        packages: tuple[str, ...],
        package_imports: tuple[str, ...],
        worker: Callable[[RealizationNode], JobResult],
    ) -> RealizationNode:
        with self._lock:
            node_id = f"job-{self._next_id}"
            self._next_id += 1
            node = RealizationNode(
                id=node_id,
                kind=kind,
                command=command,
                packages=packages,
                package_imports=package_imports,
            )
            self._nodes[node_id] = node

        thread = threading.Thread(target=self._run_node, args=(node, worker), name=f"vsandbox-{node_id}", daemon=True)
        node.thread = thread
        thread.start()
        return node

    def _run_node(self, node: RealizationNode, worker: Callable[[RealizationNode], JobResult]) -> None:
        with self._lock:
            node.state = "running"
            node.started_at = time.monotonic()
        try:
            result = worker(node)
            with self._lock:
                node.returncode = result.returncode
                node.stdout = result.stdout
                node.stderr = result.stderr
                if result.returncode == 0:
                    node.state = "succeeded"
                else:
                    node.state = "failed"
                    node.error = f"realizer exited with status {result.returncode}"
        except BaseException as exc:  # pragma: no cover - defensive thread boundary
            with self._lock:
                node.returncode = 1
                node.stderr = str(exc)
                node.error = repr(exc)
                node.state = "failed"
        finally:
            with self._lock:
                node.finished_at = time.monotonic()
            node.event.set()

    def get(self, node_id: str) -> RealizationNode | None:
        with self._lock:
            return self._nodes.get(node_id)

    def unfinished(self) -> list[RealizationNode]:
        with self._lock:
            return [node for node in self._nodes.values() if not node.is_finished]

    def jobs_for_imports(self, imports: tuple[str, ...]) -> list[RealizationNode]:
        wanted = {name for name in imports if name}
        with self._lock:
            nodes = [node for node in self._nodes.values() if not node.is_finished]
        if not wanted:
            return nodes

        selected: list[RealizationNode] = []
        for node in nodes:
            provided = set(node.package_imports)
            if not provided or wanted.intersection(provided):
                selected.append(node)
        return selected

    def wait_for(self, nodes: list[RealizationNode]) -> list[RealizationNode]:
        for node in nodes:
            node.event.wait()
        return nodes

    def snapshot(self) -> list[dict[str, object]]:
        with self._lock:
            return [node.snapshot() for node in self._nodes.values()]

