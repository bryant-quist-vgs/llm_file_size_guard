#!/usr/bin/env python3
"""LLM-maintained file size guard, built against contract v3."""

from __future__ import annotations

import argparse
import sys

from llm_file_size_guard_commands import (
    command_accept,
    command_check,
    command_clear,
    command_config_show,
    command_defer,
)
from llm_file_size_guard_config import load_configuration, resolve_state_path
from llm_file_size_guard_core import (
    DEFAULT_THRESHOLDS,
    UsageError,
    discover_repo_identity,
    discover_repo_root,
)


COMMON_OPTION_DESTS = {
    "repo",
    "state",
    "warn_lines",
    "fail_lines",
    "words_per_line",
    "chars_per_line",
    "growth_lines",
    "defer_days",
    "extensions",
    "ignore_dirs",
    "no_config",
}

DEFAULT_OPTIONS = {
    "repo": ".",
    "state": None,
    "extensions": None,
    "ignore_dirs": None,
    "local_state_dir": None,
    "no_config": False,
    **DEFAULT_THRESHOLDS,
}


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return parsed


def add_common_arguments(parser: argparse.ArgumentParser, *, defaults: bool) -> None:
    default = argparse.SUPPRESS
    parser.add_argument("--repo", default=default)
    parser.add_argument("--state", default=default, help="exact guard state path; default is central per-repo state")
    parser.add_argument("--warn-lines", type=positive_int, default=default)
    parser.add_argument("--fail-lines", type=positive_int, default=default)
    parser.add_argument("--words-per-line", type=positive_int, default=default)
    parser.add_argument("--chars-per-line", type=positive_int, default=default)
    parser.add_argument("--growth-lines", type=positive_int, default=default)
    parser.add_argument("--defer-days", type=positive_int, default=default)
    parser.add_argument("--extensions", default=default, help="comma-separated extension allow-list")
    parser.add_argument(
        "--ignore-dirs",
        default=default,
        help="comma-separated repository-relative directories to exclude from scanning",
    )
    parser.add_argument("--no-config", action="store_true", default=default, help="ignore central and repo config files")


def add_check_display_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--blocking-only",
        action="store_true",
        default=argparse.SUPPRESS,
        help="show only hard-limit (ERROR) findings; report how many warnings were hidden",
    )
    parser.add_argument(
        "--tree",
        action="store_true",
        default=argparse.SUPPRESS,
        help="append a directory-tree summary of the displayed findings",
    )


def build_parser() -> argparse.ArgumentParser:
    root_common = argparse.ArgumentParser(add_help=False)
    add_common_arguments(root_common, defaults=True)
    add_check_display_arguments(root_common)
    subcommand_common = argparse.ArgumentParser(add_help=False)
    add_common_arguments(subcommand_common, defaults=False)

    parser = argparse.ArgumentParser(
        description="Report oversized Git-tracked files before they become hard for LLMs to manage.",
        parents=[root_common],
    )
    subparsers = parser.add_subparsers(dest="command")
    check = subparsers.add_parser("check", parents=[subcommand_common], help="scan tracked maintained text files")
    add_check_display_arguments(check)
    defer = subparsers.add_parser("defer", parents=[subcommand_common], help="temporarily defer warning-level files")
    defer.add_argument("files", nargs="+")
    defer.add_argument("--reason", help="human context to store in the state")
    accept = subparsers.add_parser("accept", parents=[subcommand_common], help="hash-lock oversized frozen files")
    accept.add_argument("files", nargs="+")
    accept.add_argument("--reason", help="human context to store in the state")
    clear = subparsers.add_parser("clear", parents=[subcommand_common], help="clear defer/accept state for files")
    clear.add_argument("files", nargs="+")
    config = subparsers.add_parser("config", parents=[subcommand_common], help="inspect guard configuration")
    config_subparsers = config.add_subparsers(dest="config_command")
    show = config_subparsers.add_parser("show", parents=[subcommand_common], help="show guard configuration")
    show.add_argument("--effective", action="store_true", help="show the merged effective configuration")
    return parser


def cli_overrides(args: argparse.Namespace) -> dict[str, object]:
    return {key: getattr(args, key) for key in COMMON_OPTION_DESTS if hasattr(args, key)}


def prepare_effective_args(args: argparse.Namespace) -> argparse.Namespace:
    repo_arg = getattr(args, "repo", DEFAULT_OPTIONS["repo"])
    repo_root = discover_repo_root(repo_arg)
    no_config = bool(getattr(args, "no_config", DEFAULT_OPTIONS["no_config"]))
    config_values, config_sources, candidate_paths = load_configuration(repo_root, no_config)

    effective = dict(DEFAULT_OPTIONS)
    effective["repo"] = repo_arg
    effective.update(config_values)
    effective.update(cli_overrides(args))

    repo_identity = discover_repo_identity(repo_root)
    state_path = resolve_state_path(
        repo_root,
        effective["state"],
        effective["local_state_dir"],
        repo_identity,
    )

    for key, value in effective.items():
        setattr(args, key, value)
    args.repo_root = repo_root
    args.repo_identity = repo_identity
    args.state_path = state_path
    args.config_sources = config_sources
    args.config_candidate_paths = candidate_paths
    return args


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args = prepare_effective_args(args)
        if args.command in (None, "check"):
            return command_check(args)
        if args.command == "defer":
            return command_defer(args)
        if args.command == "accept":
            return command_accept(args)
        if args.command == "clear":
            return command_clear(args)
        if args.command == "config":
            if args.config_command == "show":
                if not args.effective:
                    raise UsageError("config show requires --effective")
                return command_config_show(args)
            raise UsageError("config requires a subcommand: show")
        raise UsageError(f"unknown command: {args.command}")
    except UsageError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
