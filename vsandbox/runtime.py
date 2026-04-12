from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
import time
import venv
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .barrier import BarrierClassifier, imports_for_python_command, pip_subprocess_args
from .graph import JobResult, RealizationGraph, RealizationNode


@dataclass(frozen=True)
class RunResult:
    command: str
    returncode: int
    stdout: str = ""
    stderr: str = ""
    elapsed_s: float = 0.0
    barrier_wait_s: float = 0.0
    logically_committed: bool = False
    physical_executed: bool = True
    jobs_waited: tuple[str, ...] = ()
    job_id: str | None = None
    classification: str = ""


class VirtualSandbox:
    def __init__(
        self,
        *,
        workspace: str | os.PathLike[str] | None = None,
        use_venv: bool = True,
        pip_realizer: Callable[[RealizationNode], JobResult] | None = None,
    ) -> None:
        self.workspace = Path(workspace) if workspace is not None else Path(tempfile.mkdtemp(prefix="vsandbox-"))
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.use_venv = use_venv
        self._state_dir = self.workspace / ".vsandbox"
        self._venv_dir = self._state_dir / "venv"
        self._classifier = BarrierClassifier()
        self._graph = RealizationGraph()
        self._overlay: dict[Path, str] = {}
        self._dirty: set[Path] = set()
        self._overlay_lock = threading.Lock()
        self._venv_lock = threading.Lock()
        self._pip_lock = threading.Lock()
        self._pip_realizer = pip_realizer

    @classmethod
    def create(
        cls,
        *,
        workspace: str | os.PathLike[str] | None = None,
        use_venv: bool = True,
        pip_realizer: Callable[[RealizationNode], JobResult] | None = None,
    ) -> "VirtualSandbox":
        return cls(workspace=workspace, use_venv=use_venv, pip_realizer=pip_realizer)

    @property
    def graph(self) -> RealizationGraph:
        return self._graph

    def run(self, command: str) -> RunResult:
        start = time.monotonic()
        classification = self._classifier.classify(command)

        if classification.is_deferred_install:
            node = self._graph.submit(
                kind="pip",
                command=command,
                packages=classification.packages,
                package_imports=classification.package_imports,
                worker=self._realize_pip_job,
            )
            elapsed = time.monotonic() - start
            stdout = (
                f"vsandbox: logically committed {node.id}; "
                f"realization running asynchronously for {command!r}\n"
            )
            return RunResult(
                command=command,
                returncode=0,
                stdout=stdout,
                elapsed_s=elapsed,
                logically_committed=True,
                physical_executed=False,
                job_id=node.id,
                classification=classification.kind,
            )

        if classification.is_metadata_observation:
            internal = self._try_metadata_observation(command, start)
            if internal is not None:
                return internal

        if classification.is_python_barrier:
            imports = imports_for_python_command(command, read_file=self._read_for_import_scan)
            jobs = self._graph.jobs_for_imports(imports or ())
        else:
            jobs = self._graph.unfinished()

        wait_s, failure = self._wait_for_barrier_jobs(jobs)
        if failure is not None:
            elapsed = time.monotonic() - start
            return RunResult(
                command=command,
                returncode=1,
                stderr=failure,
                elapsed_s=elapsed,
                barrier_wait_s=wait_s,
                physical_executed=False,
                jobs_waited=tuple(node.id for node in jobs),
                classification=classification.kind,
            )

        self.flush_overlay()
        if classification.is_python_barrier:
            self._ensure_venv()
        result = self._execute_shell(command)
        elapsed = time.monotonic() - start
        return RunResult(
            command=command,
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            elapsed_s=elapsed,
            barrier_wait_s=wait_s,
            jobs_waited=tuple(node.id for node in jobs),
            classification=classification.kind,
        )

    def write_file(self, path: str | os.PathLike[str], content: str) -> None:
        rel = self._normalize_logical_path(path)
        with self._overlay_lock:
            self._overlay[rel] = content
            self._dirty.add(rel)

    def read_file(self, path: str | os.PathLike[str]) -> str:
        rel = self._normalize_logical_path(path)
        with self._overlay_lock:
            if rel in self._overlay:
                return self._overlay[rel]
        physical = self.workspace / rel
        return physical.read_text(encoding="utf-8")

    def flush_overlay(self) -> list[Path]:
        with self._overlay_lock:
            dirty = list(self._dirty)
            contents = {rel: self._overlay[rel] for rel in dirty}
            self._dirty.clear()
        flushed: list[Path] = []
        for rel, content in contents.items():
            physical = self.workspace / rel
            physical.parent.mkdir(parents=True, exist_ok=True)
            physical.write_text(content, encoding="utf-8")
            flushed.append(physical)
        return flushed

    def status(self) -> dict[str, object]:
        with self._overlay_lock:
            dirty_files = sorted(str(path) for path in self._dirty)
        return {
            "workspace": str(self.workspace),
            "use_venv": self.use_venv,
            "dirty_files": dirty_files,
            "jobs": self._graph.snapshot(),
        }

    def shutdown(self, *, wait: bool = True) -> None:
        if wait:
            self._graph.wait_for(self._graph.unfinished())
        self.flush_overlay()

    def _realize_pip_job(self, node: RealizationNode) -> JobResult:
        if self._pip_realizer is not None:
            return self._pip_realizer(node)
        with self._pip_lock:
            self._ensure_venv()
            args = pip_subprocess_args(node.command, self._python_executable())
            completed = subprocess.run(
                args,
                cwd=self.workspace,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=900,
            )
            return JobResult(completed.returncode, completed.stdout, completed.stderr)

    def _wait_for_barrier_jobs(self, jobs: list[RealizationNode]) -> tuple[float, str | None]:
        if not jobs:
            return 0.0, None
        start = time.monotonic()
        self._graph.wait_for(jobs)
        wait_s = time.monotonic() - start
        failed = [node for node in jobs if node.state == "failed"]
        if not failed:
            return wait_s, None
        lines = ["vsandbox: deferred realization failed before execution:"]
        for node in failed:
            stderr = node.stderr.strip()
            detail = stderr.splitlines()[-1] if stderr else (node.error or "unknown error")
            lines.append(
                f"- {node.id} after {node.elapsed_s:.3f}s: {node.command!r}: {detail}"
            )
        return wait_s, "\n".join(lines) + "\n"

    def _execute_shell(self, command: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        if self.use_venv and self._venv_python_path().exists():
            env["VIRTUAL_ENV"] = str(self._venv_dir)
            env["PATH"] = str(self._venv_dir / "bin") + os.pathsep + env.get("PATH", "")
        return subprocess.run(
            command,
            shell=True,
            cwd=self.workspace,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def _try_metadata_observation(self, command: str, start: float) -> RunResult | None:
        try:
            import shlex

            tokens = shlex.split(command)
        except ValueError:
            return None
        if not tokens:
            return RunResult(command=command, returncode=0, elapsed_s=time.monotonic() - start)

        head = Path(tokens[0]).name
        if head == "pwd" and len(tokens) == 1:
            return RunResult(
                command=command,
                returncode=0,
                stdout=str(self.workspace) + "\n",
                elapsed_s=time.monotonic() - start,
                classification="metadata_observation",
            )

        if head == "cat" and len(tokens) >= 2 and not any(token.startswith("-") for token in tokens[1:]):
            try:
                stdout = "".join(self.read_file(token) for token in tokens[1:])
            except OSError:
                return None
            return RunResult(
                command=command,
                returncode=0,
                stdout=stdout,
                elapsed_s=time.monotonic() - start,
                classification="metadata_observation",
            )

        if head == "ls":
            paths = [token for token in tokens[1:] if not token.startswith("-")] or ["."]
            try:
                stdout = self._logical_ls(paths)
            except OSError:
                return None
            return RunResult(
                command=command,
                returncode=0,
                stdout=stdout,
                elapsed_s=time.monotonic() - start,
                classification="metadata_observation",
            )
        return None

    def _logical_ls(self, paths: list[str]) -> str:
        sections: list[str] = []
        multiple = len(paths) > 1
        with self._overlay_lock:
            overlay_paths = set(self._overlay)

        for raw in paths:
            rel = self._normalize_logical_path(raw)
            physical = self.workspace / rel
            names: set[str] = set()
            if physical.is_file() or rel in overlay_paths:
                names.add(rel.name)
            else:
                if physical.exists():
                    names.update(child.name for child in physical.iterdir())
                prefix = Path(".") if str(rel) == "." else rel
                for overlay in overlay_paths:
                    try:
                        remainder = overlay.relative_to(prefix)
                    except ValueError:
                        continue
                    if remainder.parts:
                        names.add(remainder.parts[0])
            body = "\n".join(sorted(names))
            if body:
                body += "\n"
            if multiple:
                sections.append(f"{raw}:\n{body}")
            else:
                sections.append(body)
        return "\n".join(sections)

    def _read_for_import_scan(self, path: str) -> str | None:
        try:
            return self.read_file(path)
        except OSError:
            return None

    def _normalize_logical_path(self, path: str | os.PathLike[str]) -> Path:
        raw = Path(path)
        if raw.is_absolute():
            try:
                raw = raw.resolve().relative_to(self.workspace.resolve())
            except ValueError as exc:
                raise ValueError(f"path {path!s} is outside sandbox workspace {self.workspace}") from exc
        normalized = Path(os.path.normpath(str(raw)))
        if str(normalized) == ".":
            return Path(".")
        if any(part == ".." for part in normalized.parts):
            raise ValueError(f"path {path!s} escapes sandbox workspace")
        return normalized

    def _ensure_venv(self) -> None:
        if not self.use_venv:
            return
        python = self._venv_python_path()
        if python.exists():
            return
        with self._venv_lock:
            if python.exists():
                return
            self._state_dir.mkdir(parents=True, exist_ok=True)
            venv.EnvBuilder(with_pip=True, clear=False).create(self._venv_dir)

    def _venv_python_path(self) -> Path:
        return self._venv_dir / "bin" / "python"

    def _python_executable(self) -> str:
        if self.use_venv:
            return str(self._venv_python_path())
        return sys.executable

