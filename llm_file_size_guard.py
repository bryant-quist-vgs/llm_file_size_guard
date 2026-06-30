#!/usr/bin/env python3
"""LLM-maintained file size guard, built against contract v2."""

from __future__ import annotations

import argparse
import sys

from llm_file_size_guard_commands import (
    command_accept,
    command_check,
    command_clear,
    command_defer,
)
from llm_file_size_guard_core import DEFAULT_STATE_FILE, UsageError


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return parsed


def add_common_arguments(parser: argparse.ArgumentParser, *, defaults: bool) -> None:
    default = None if defaults else argparse.SUPPRESS
    parser.add_argument("--repo", default="." if defaults else argparse.SUPPRESS)
    parser.add_argument("--state", default=default, help=f"guard state path, default {DEFAULT_STATE_FILE}")
    parser.add_argument("--warn-lines", type=positive_int, default=500 if defaults else argparse.SUPPRESS)
    parser.add_argument("--fail-lines", type=positive_int, default=800 if defaults else argparse.SUPPRESS)
    parser.add_argument("--words-per-line", type=positive_int, default=10 if defaults else argparse.SUPPRESS)
    parser.add_argument("--chars-per-line", type=positive_int, default=80 if defaults else argparse.SUPPRESS)
    parser.add_argument("--growth-lines", type=positive_int, default=100 if defaults else argparse.SUPPRESS)
    parser.add_argument("--defer-days", type=positive_int, default=7 if defaults else argparse.SUPPRESS)
    parser.add_argument("--extensions", default=default, help="comma-separated extension allow-list")


def build_parser() -> argparse.ArgumentParser:
    root_common = argparse.ArgumentParser(add_help=False)
    add_common_arguments(root_common, defaults=True)
    subcommand_common = argparse.ArgumentParser(add_help=False)
    add_common_arguments(subcommand_common, defaults=False)

    parser = argparse.ArgumentParser(
        description="Report oversized Git-tracked files before they become hard for LLMs to manage.",
        parents=[root_common],
    )
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("check", parents=[subcommand_common], help="scan tracked maintained text files")
    defer = subparsers.add_parser("defer", parents=[subcommand_common], help="temporarily defer warning-level files")
    defer.add_argument("files", nargs="+")
    defer.add_argument("--reason", help="human context to store in the state")
    accept = subparsers.add_parser("accept", parents=[subcommand_common], help="hash-lock oversized frozen files")
    accept.add_argument("files", nargs="+")
    accept.add_argument("--reason", help="human context to store in the state")
    clear = subparsers.add_parser("clear", parents=[subcommand_common], help="clear defer/accept state for files")
    clear.add_argument("files", nargs="+")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command in (None, "check"):
            return command_check(args)
        if args.command == "defer":
            return command_defer(args)
        if args.command == "accept":
            return command_accept(args)
        if args.command == "clear":
            return command_clear(args)
        raise UsageError(f"unknown command: {args.command}")
    except UsageError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
