"""CLI command handlers for llm_file_size_guard.py, built against contract v1."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

from llm_file_size_guard_config import default_state_dir
from llm_file_size_guard_core import (
    COMMAND_NAME,
    DEFAULT_STATE_SCHEMA_VERSION,
    Finding,
    Metrics,
    Thresholds,
    UsageError,
    accepted_hash_changed_note,
    active_accept,
    active_defer,
    classify_snapshot,
    format_timestamp,
    load_state,
    metric_items,
    metrics_to_dict,
    parse_extensions,
    scan_repo,
    utc_now,
    write_state,
)


def format_metrics(metrics: Metrics) -> str:
    return ", ".join(f"{name}={value}" for name, value in metric_items(metrics))


def format_broken(broken: dict[str, tuple[int, int]]) -> str:
    return "; ".join(f"{name} {value} > {limit}" for name, (value, limit) in broken.items())


def print_findings(visible: list[Finding], accepted_count: int, deferred_count: int) -> None:
    if not visible:
        print("No unsuppressed file size findings.")
    for finding in visible:
        print(f"{finding.severity}: {finding.path}")
        if finding.note:
            print(f"  note: {finding.note}")
        print(f"  metrics: {format_metrics(finding.metrics)}")
        print(f"  breaks: {format_broken(finding.broken)}")
    if accepted_count:
        print(f"Suppressed {accepted_count} accepted file(s).")
    if deferred_count:
        print(f"Suppressed {deferred_count} deferred warning(s).")


def build_thresholds(args: Any) -> Thresholds:
    if args.fail_lines <= args.warn_lines:
        raise UsageError("--fail-lines must be greater than --warn-lines")
    return Thresholds(
        warn_lines=args.warn_lines,
        fail_lines=args.fail_lines,
        words_per_line=args.words_per_line,
        chars_per_line=args.chars_per_line,
        growth_lines=args.growth_lines,
    )


def command_check(args: Any) -> int:
    thresholds = build_thresholds(args)
    extensions = parse_extensions(args.extensions)
    repo_root = args.repo_root
    state = load_state(args.state_path, args.repo_identity)
    scan = scan_repo(repo_root, extensions)
    visible: list[Finding] = []
    accepted_count = 0
    deferred_count = 0
    now = utc_now()

    for path, reason in sorted(scan.skipped.items()):
        print(f"Skipped {path}: {reason}", file=sys.stderr)

    for snapshot in scan.snapshots:
        finding = classify_snapshot(snapshot, thresholds)
        if finding is None:
            continue
        if active_accept(snapshot, state):
            accepted_count += 1
        elif active_defer(finding, state, thresholds, now, args.defer_days):
            deferred_count += 1
        else:
            note = accepted_hash_changed_note(snapshot, state)
            if note:
                finding = Finding(finding.path, finding.severity, finding.metrics, finding.broken, note)
            visible.append(finding)

    print_findings(visible, accepted_count, deferred_count)
    return 1 if any(finding.severity == "ERROR" for finding in visible) else 0


def repo_relative_input(repo_root: Path, raw_path: str) -> str:
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = repo_root / candidate
    resolved = candidate.resolve()
    try:
        relative = resolved.relative_to(repo_root)
    except ValueError as exc:
        raise UsageError(f"path is outside repository: {raw_path}") from exc
    return relative.as_posix()


def command_defer(args: Any) -> int:
    thresholds = build_thresholds(args)
    extensions = parse_extensions(args.extensions)
    repo_root = args.repo_root
    state_path = args.state_path
    state = load_state(state_path, args.repo_identity)
    scan = scan_repo(repo_root, extensions)
    snapshots = {snapshot.path: snapshot for snapshot in scan.snapshots}
    failed = False
    now = utc_now()

    for raw_path in args.files:
        rel_path = repo_relative_input(repo_root, raw_path)
        if rel_path not in scan.tracked_paths:
            print(f"Cannot defer {rel_path}: not tracked by git")
            failed = True
            continue
        snapshot = snapshots.get(rel_path)
        if snapshot is None:
            reason = scan.skipped.get(rel_path, "not a selected maintained text file")
            print(f"Cannot defer {rel_path}: {reason}")
            failed = True
            continue
        finding = classify_snapshot(snapshot, thresholds)
        if finding is None:
            print(f"Cannot defer {rel_path}: below review threshold")
            failed = True
            continue
        if finding.severity == "ERROR":
            print(f"Cannot defer {rel_path}: exceeds hard-split threshold; use accept for frozen files")
            failed = True
            continue

        record: dict[str, Any] = {
            "sha256": snapshot.sha256,
            "deferred_at": format_timestamp(now),
            "metrics": metrics_to_dict(snapshot.metrics),
            "thresholds": {
                "warn": metrics_to_dict(thresholds.warn_limits()),
                "fail": metrics_to_dict(thresholds.fail_limits()),
                "growth": metrics_to_dict(thresholds.growth_limits()),
            },
        }
        if args.reason:
            record["reason"] = args.reason
        state.setdefault("deferred", {})[rel_path] = record
        state.setdefault("accepted", {}).pop(rel_path, None)
        print(f"Deferred {rel_path}: {format_metrics(snapshot.metrics)}")

    if state.get("deferred") or state.get("accepted"):
        write_state(state_path, state)
    return 1 if failed else 0


def command_accept(args: Any) -> int:
    thresholds = build_thresholds(args)
    extensions = parse_extensions(args.extensions)
    repo_root = args.repo_root
    state_path = args.state_path
    state = load_state(state_path, args.repo_identity)
    scan = scan_repo(repo_root, extensions)
    snapshots = {snapshot.path: snapshot for snapshot in scan.snapshots}
    failed = False
    now = utc_now()

    for raw_path in args.files:
        rel_path = repo_relative_input(repo_root, raw_path)
        if rel_path not in scan.tracked_paths:
            print(f"Cannot accept {rel_path}: not tracked by git")
            failed = True
            continue
        snapshot = snapshots.get(rel_path)
        if snapshot is None:
            reason = scan.skipped.get(rel_path, "not a selected maintained text file")
            print(f"Cannot accept {rel_path}: {reason}")
            failed = True
            continue
        if classify_snapshot(snapshot, thresholds) is None:
            print(f"Cannot accept {rel_path}: below review threshold")
            failed = True
            continue
        record = {
            "sha256": snapshot.sha256,
            "accepted_at": format_timestamp(now),
            "metrics": metrics_to_dict(snapshot.metrics),
            "thresholds": {
                "warn": metrics_to_dict(thresholds.warn_limits()),
                "fail": metrics_to_dict(thresholds.fail_limits()),
            },
        }
        if args.reason:
            record["reason"] = args.reason
        state.setdefault("accepted", {})[rel_path] = record
        state.setdefault("deferred", {}).pop(rel_path, None)
        print(f"Accepted {rel_path}: {format_metrics(snapshot.metrics)}, sha256={snapshot.sha256[:12]}")

    if state.get("deferred") or state.get("accepted"):
        write_state(state_path, state)
    return 1 if failed else 0


def command_clear(args: Any) -> int:
    repo_root = args.repo_root
    state_path = args.state_path
    state = load_state(state_path, args.repo_identity)
    changed = False
    for raw_path in args.files:
        rel_path = repo_relative_input(repo_root, raw_path)
        removed = False
        for bucket in ("deferred", "accepted"):
            if state.setdefault(bucket, {}).pop(rel_path, None) is not None:
                removed = True
                changed = True
        print(f"Cleared {rel_path}" if removed else f"No state for {rel_path}")
    if changed:
        write_state(state_path, state)
    return 0


def command_config_show(args: Any) -> int:
    extensions = sorted(parse_extensions(args.extensions))
    local_state_dir = args.local_state_dir or str(default_state_dir())
    report = {
        "command": COMMAND_NAME,
        "repo_root": str(args.repo_root),
        "repo": args.repo_identity.metadata(),
        "config": {
            "no_config": args.no_config,
            "loaded": [str(path) for path in args.config_sources],
            "candidates": [str(path) for path in args.config_candidate_paths],
        },
        "thresholds": {
            "warn_lines": args.warn_lines,
            "fail_lines": args.fail_lines,
            "words_per_line": args.words_per_line,
            "chars_per_line": args.chars_per_line,
            "growth_lines": args.growth_lines,
            "defer_days": args.defer_days,
        },
        "selection": {
            "extensions": extensions,
        },
        "tracking": {
            "schema_version": DEFAULT_STATE_SCHEMA_VERSION,
            "local_state_dir": local_state_dir,
            "state_path": str(args.state_path),
        },
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0
