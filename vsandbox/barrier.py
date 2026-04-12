from __future__ import annotations

import ast
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


PYTHON_COMMANDS = {"python", "python3"}
TEST_COMMANDS = {"pytest", "py.test", "tox", "nox"}
PIP_COMMANDS = {"pip", "pip3"}

_SHELL_META_RE = re.compile(r"[;&|<>]")
_PYTHON_VERSION_RE = re.compile(r"^python3(?:\.\d+)?$")
_PACKAGE_SPLIT_RE = re.compile(r"[<>=!~\[]")

_OPTIONS_WITH_VALUE = {
    "-c",
    "--constraint",
    "-f",
    "--find-links",
    "-i",
    "--index-url",
    "--extra-index-url",
    "--prefix",
    "--root",
    "-r",
    "--requirement",
    "-t",
    "--target",
}

_IMPORT_ALIASES = {
    "beautifulsoup4": "bs4",
    "opencv_python": "cv2",
    "opencv_python_headless": "cv2",
    "pillow": "PIL",
    "protobuf": "google",
    "pyyaml": "yaml",
    "python_dateutil": "dateutil",
    "scikit_learn": "sklearn",
}


@dataclass(frozen=True)
class CommandClassification:
    kind: str
    packages: tuple[str, ...] = ()
    package_imports: tuple[str, ...] = ()
    reason: str = ""

    @property
    def is_deferred_install(self) -> bool:
        return self.kind == "pip_install"

    @property
    def is_python_barrier(self) -> bool:
        return self.kind == "python_execution"

    @property
    def is_metadata_observation(self) -> bool:
        return self.kind == "metadata_observation"


class BarrierClassifier:
    """Classifies a narrow, conservative subset of shell commands."""

    def classify(self, command: str) -> CommandClassification:
        tokens = _safe_split(command)
        if not tokens:
            return CommandClassification(kind="noop", reason="empty command")

        pip_args = _pure_pip_install_args(command, tokens)
        if pip_args is not None:
            packages = tuple(_pip_install_packages(pip_args))
            package_imports = tuple(
                sorted({name for package in packages for name in package_to_imports(package)})
            )
            return CommandClassification(
                kind="pip_install",
                packages=packages,
                package_imports=package_imports,
                reason="pure pip install command",
            )

        head = _basename(tokens[0])
        if _is_python_name(head) or head in TEST_COMMANDS:
            return CommandClassification(kind="python_execution", reason=f"{head} execution barrier")

        if head in {"cat", "ls", "pwd", "test"}:
            return CommandClassification(kind="metadata_observation", reason=f"{head} observation")

        return CommandClassification(kind="external_execution", reason="conservative execution barrier")


def _safe_split(command: str) -> list[str]:
    try:
        return shlex.split(command, posix=True)
    except ValueError:
        return []


def _basename(value: str) -> str:
    return Path(value).name


def _is_python_name(value: str) -> bool:
    return value in PYTHON_COMMANDS or bool(_PYTHON_VERSION_RE.match(value))


def _pure_pip_install_args(command: str, tokens: list[str]) -> list[str] | None:
    if _SHELL_META_RE.search(command):
        return None
    if not tokens:
        return None

    head = _basename(tokens[0])
    if head in PIP_COMMANDS:
        if len(tokens) >= 2 and tokens[1] in {"install", "sync", "add"}:
            return tokens[1:]
        return None

    if _is_python_name(head) and len(tokens) >= 5 and tokens[1:4] == ["-m", "pip", "install"]:
        return tokens[3:]
    return None


def pip_subprocess_args(command: str, python_executable: str) -> list[str]:
    tokens = _safe_split(command)
    pip_args = _pure_pip_install_args(command, tokens)
    if pip_args is None:
        raise ValueError(f"not a pure pip install command: {command!r}")
    return [python_executable, "-m", "pip", *pip_args]


def _pip_install_packages(pip_args: list[str]) -> list[str]:
    packages: list[str] = []
    skip_next = False
    # pip_args includes the subcommand, normally "install".
    for arg in pip_args[1:]:
        if skip_next:
            skip_next = False
            continue
        if arg == "--":
            continue
        if arg in _OPTIONS_WITH_VALUE:
            skip_next = True
            continue
        if any(arg.startswith(prefix + "=") for prefix in _OPTIONS_WITH_VALUE if prefix.startswith("--")):
            continue
        if arg.startswith("-"):
            continue
        packages.append(arg)
    return packages


def package_to_imports(package: str) -> tuple[str, ...]:
    raw = package.strip()
    if not raw or raw.startswith((".", "/", "git+", "http://", "https://")):
        return ()
    if raw.endswith((".whl", ".tar.gz", ".zip")):
        return ()
    name = _PACKAGE_SPLIT_RE.split(raw, maxsplit=1)[0].strip()
    if not name:
        return ()
    normalized = re.sub(r"[-.]+", "_", name).strip("_")
    if not normalized:
        return ()
    return (_IMPORT_ALIASES.get(normalized.lower(), normalized),)


def extract_imports_from_source(source: str) -> tuple[str, ...]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return tuple(sorted(_regex_imports(source)))

    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.level == 0:
                imports.add(node.module.split(".", 1)[0])
    return tuple(sorted(imports))


def _regex_imports(source: str) -> set[str]:
    imports: set[str] = set()
    for match in re.finditer(r"(?m)^\s*(?:from\s+([A-Za-z_][\w.]*)|import\s+([A-Za-z_][\w.]*))", source):
        name = match.group(1) or match.group(2)
        imports.add(name.split(".", 1)[0])
    return imports


def imports_for_python_command(
    command: str,
    *,
    read_file: Callable[[str], str | None],
) -> tuple[str, ...] | None:
    tokens = _safe_split(command)
    if not tokens:
        return None
    head = _basename(tokens[0])
    if head in TEST_COMMANDS:
        return ()
    if not _is_python_name(head):
        return None

    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token == "-c" and index + 1 < len(tokens):
            return extract_imports_from_source(tokens[index + 1])
        if token == "-m" and index + 1 < len(tokens):
            module = tokens[index + 1].split(".", 1)[0]
            return (module,) if module else ()
        if token.startswith("-"):
            index += 1
            continue
        if token.endswith(".py"):
            source = read_file(token)
            return extract_imports_from_source(source) if source is not None else ()
        return ()
    return ()


def trace_command_has_pip_install(command: str) -> bool:
    pattern = re.compile(
        r"(?:^|[;&|\s])(?:uv\s+pip|python(?:3(?:\.\d+)?)?\s+-m\s+pip|pip3?|pipx)\s+"
        r"(?:install|sync|add)\b|\bpoetry\s+(?:add|install)\b|\bpipenv\s+install\b",
        re.IGNORECASE,
    )
    return bool(pattern.search(command))


def trace_command_is_python_barrier(command: str) -> bool:
    pattern = re.compile(
        r"(?:^|[;&|\s])(?:python(?:3(?:\.\d+)?)?|pytest|py\.test|ipython|jupyter|streamlit|"
        r"uv\s+run\s+python|uv\s+run\s+pytest)\b|\b(?:tox|nox|coverage\s+run)\b",
        re.IGNORECASE,
    )
    return bool(pattern.search(command))

