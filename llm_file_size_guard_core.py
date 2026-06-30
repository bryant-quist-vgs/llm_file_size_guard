"""Core implementation for llm_file_size_guard.py, built against contract v2."""

from __future__ import annotations

from dataclasses import dataclass
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any


DEFAULT_STATE_FILE = ".llm_file_size_guard_state.json"
DEFAULT_EXTENSIONS = frozenset(
    f".{ext}"
    for ext in (
        "bash c cc cfg cjs clj cpp cs css cxx fish go h hpp html ini java js json jsx "
        "kt kts lua md mdx mjs php pl pm py pyw r rb rs rst scala scss sh sql swift "
        "toml ts tsx txt yaml yml zsh"
    ).split()
)
KNOWN_SCRIPT_NAMES = frozenset(
    "Brewfile Containerfile Dockerfile Gemfile Jenkinsfile Makefile Rakefile Vagrantfile".split()
)
WORD_RE = re.compile(r"\S+")


@dataclass(frozen=True)
class Metrics:
    lines: int
    words: int
    characters: int


@dataclass(frozen=True)
class Thresholds:
    warn_lines: int
    fail_lines: int
    words_per_line: int
    chars_per_line: int
    growth_lines: int

    def warn_limits(self) -> Metrics:
        return self.line_equivalent(self.warn_lines)

    def fail_limits(self) -> Metrics:
        return self.line_equivalent(self.fail_lines)

    def growth_limits(self) -> Metrics:
        return self.line_equivalent(self.growth_lines)

    def line_equivalent(self, lines: int) -> Metrics:
        return Metrics(
            lines=lines,
            words=lines * self.words_per_line,
            characters=lines * self.chars_per_line,
        )


@dataclass(frozen=True)
class FileSnapshot:
    path: str
    metrics: Metrics
    sha256: str


@dataclass(frozen=True)
class Finding:
    path: str
    severity: str
    metrics: Metrics
    broken: dict[str, tuple[int, int]]
    note: str | None = None


@dataclass(frozen=True)
class ScanResult:
    snapshots: list[FileSnapshot]
    skipped: dict[str, str]
    tracked_paths: set[str]


class UsageError(Exception):
    pass


def metric_items(metrics: Metrics) -> tuple[tuple[str, int], ...]:
    return (
        ("lines", metrics.lines),
        ("words", metrics.words),
        ("characters", metrics.characters),
    )


def metric_value(metrics: Metrics, name: str) -> int:
    return getattr(metrics, name)


def metrics_to_dict(metrics: Metrics) -> dict[str, int]:
    return {name: value for name, value in metric_items(metrics)}


def metrics_from_mapping(value: Any) -> Metrics | None:
    if not isinstance(value, dict):
        return None
    try:
        lines = value["lines"]
        words = value["words"]
        characters = value["characters"]
    except KeyError:
        return None
    if not all(isinstance(item, int) for item in (lines, words, characters)):
        return None
    return Metrics(lines=lines, words=words, characters=characters)


def parse_extensions(raw: str | None) -> frozenset[str]:
    if raw is None:
        return DEFAULT_EXTENSIONS
    extensions: set[str] = set()
    for part in raw.split(","):
        extension = part.strip().lower()
        if not extension:
            continue
        if not extension.startswith("."):
            extension = "." + extension
        extensions.add(extension)
    if not extensions:
        raise UsageError("--extensions must include at least one extension")
    return frozenset(extensions)


def run_git(repo: Path, args: list[str]) -> bytes:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo), *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
    except FileNotFoundError as exc:
        raise UsageError("git executable was not found on PATH") from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", errors="replace").strip()
        detail = f": {stderr}" if stderr else ""
        raise UsageError(f"git {' '.join(args)} failed{detail}") from exc
    return completed.stdout


def discover_repo_root(repo: str) -> Path:
    candidate = Path(repo).expanduser()
    output = run_git(candidate, ["rev-parse", "--show-toplevel"])
    try:
        root_text = output.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise UsageError("git returned a non-UTF-8 repository path") from exc
    if not root_text:
        raise UsageError("git did not return a repository root")
    return Path(root_text).resolve()


def tracked_paths(repo_root: Path) -> list[str]:
    output = run_git(repo_root, ["ls-files", "-z"])
    try:
        decoded = output.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UsageError("git ls-files returned non-UTF-8 paths") from exc
    return sorted(path for path in decoded.split("\0") if path)


def resolve_state_path(repo_root: Path, state: str | None) -> Path:
    if state is None:
        return repo_root / DEFAULT_STATE_FILE
    path = Path(state).expanduser()
    if not path.is_absolute():
        path = repo_root / path
    return path.resolve()


def is_selected_tracked_file(path: Path, rel_path: str, extensions: frozenset[str]) -> bool:
    if path.is_symlink():
        return False
    rel = Path(rel_path)
    if rel.name in KNOWN_SCRIPT_NAMES:
        return True
    if rel.suffix.lower() in extensions:
        return True
    try:
        with path.open("rb") as handle:
            return handle.read(2) == b"#!"
    except OSError:
        return False


def count_payload(payload: bytes) -> tuple[Metrics, str]:
    text = payload.decode("utf-8")
    metrics = Metrics(
        lines=0 if text == "" else len(text.splitlines()),
        words=len(WORD_RE.findall(text)),
        characters=len(text),
    )
    return metrics, hashlib.sha256(payload).hexdigest()


def scan_repo(repo_root: Path, extensions: frozenset[str]) -> ScanResult:
    snapshots: list[FileSnapshot] = []
    skipped: dict[str, str] = {}
    tracked = set(tracked_paths(repo_root))
    for rel_path in sorted(tracked):
        path = repo_root / rel_path
        if not is_selected_tracked_file(path, rel_path, extensions):
            continue
        try:
            payload = path.read_bytes()
            metrics, digest = count_payload(payload)
        except UnicodeDecodeError:
            skipped[rel_path] = "not UTF-8 text"
            continue
        except OSError as exc:
            skipped[rel_path] = str(exc)
            continue
        snapshots.append(FileSnapshot(path=rel_path, metrics=metrics, sha256=digest))
    return ScanResult(snapshots=snapshots, skipped=skipped, tracked_paths=tracked)


def broken_metrics(metrics: Metrics, limits: Metrics) -> dict[str, tuple[int, int]]:
    broken: dict[str, tuple[int, int]] = {}
    for name, value in metric_items(metrics):
        limit = metric_value(limits, name)
        if value > limit:
            broken[name] = (value, limit)
    return broken


def classify_snapshot(snapshot: FileSnapshot, thresholds: Thresholds) -> Finding | None:
    fail_broken = broken_metrics(snapshot.metrics, thresholds.fail_limits())
    if fail_broken:
        return Finding(
            path=snapshot.path,
            severity="ERROR",
            metrics=snapshot.metrics,
            broken=fail_broken,
        )
    warn_broken = broken_metrics(snapshot.metrics, thresholds.warn_limits())
    if warn_broken:
        return Finding(
            path=snapshot.path,
            severity="WARNING",
            metrics=snapshot.metrics,
            broken=warn_broken,
        )
    return None


def empty_state() -> dict[str, Any]:
    return {"version": 2, "deferred": {}, "accepted": {}}


def normalize_state(data: dict[str, Any], path: Path) -> dict[str, Any]:
    deferred = data.get("deferred")
    if deferred is None and isinstance(data.get("snoozes"), dict):
        deferred = {}
        for rel_path, record in data["snoozes"].items():
            if isinstance(record, dict):
                migrated = dict(record)
                migrated["deferred_at"] = migrated.get("deferred_at") or migrated.get("snoozed_at")
                deferred[rel_path] = migrated
    if deferred is None:
        deferred = {}
    accepted = data.get("accepted")
    if accepted is None:
        accepted = {}
    if not isinstance(deferred, dict):
        raise UsageError(f"state file {path} field 'deferred' must be an object")
    if not isinstance(accepted, dict):
        raise UsageError(f"state file {path} field 'accepted' must be an object")
    return {"version": 2, "deferred": deferred, "accepted": accepted}


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return empty_state()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise UsageError(f"could not read state file {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise UsageError(f"state file {path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise UsageError(f"state file {path} must contain a JSON object")
    return normalize_state(data, path)


def write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC).replace(microsecond=0)


def format_timestamp(value: dt.datetime) -> str:
    return value.astimezone(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_timestamp(value: Any) -> dt.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed.astimezone(dt.UTC)


def active_defer(
    finding: Finding,
    state: dict[str, Any],
    thresholds: Thresholds,
    now: dt.datetime,
    defer_days: int,
) -> bool:
    if finding.severity != "WARNING":
        return False
    record = state.get("deferred", {}).get(finding.path)
    if not isinstance(record, dict):
        return False
    deferred_at = parse_timestamp(record.get("deferred_at"))
    if deferred_at is None:
        return False
    if now - deferred_at > dt.timedelta(days=defer_days):
        return False
    baseline = metrics_from_mapping(record.get("metrics"))
    if baseline is None:
        return False
    growth = thresholds.growth_limits()
    for name, current in metric_items(finding.metrics):
        if current - metric_value(baseline, name) > metric_value(growth, name):
            return False
    return True


def active_accept(snapshot: FileSnapshot, state: dict[str, Any]) -> bool:
    record = state.get("accepted", {}).get(snapshot.path)
    return isinstance(record, dict) and record.get("sha256") == snapshot.sha256


def accepted_hash_changed_note(snapshot: FileSnapshot, state: dict[str, Any]) -> str | None:
    record = state.get("accepted", {}).get(snapshot.path)
    if not isinstance(record, dict):
        return None
    accepted_hash = record.get("sha256")
    if not isinstance(accepted_hash, str) or accepted_hash == snapshot.sha256:
        return None
    return f"accepted hash changed ({accepted_hash[:12]} -> {snapshot.sha256[:12]})"

