#!/usr/bin/env python3
"""llm_file_size_guard_test.py - Tests for llm_file_size_guard.py, built against contract v1.

Coverage:
  - Happy path: reports warning and hard-limit findings for tracked maintained files.
  - Load-bearing: line, word, and character thresholds all produce findings.
  - Load-bearing: layered TOML config can set thresholds and central state location.
  - Load-bearing: untracked files are ignored.
  - Load-bearing: central v1 state includes repository identity metadata.
  - Load-bearing: deferred warnings reappear after age, line, or character growth.
  - Load-bearing: accepted files suppress warnings and hard-limit errors only while the hash matches.
  - Load-bearing: clear removes either deferred or accepted state.
  - Load-bearing: config show reports the effective merged configuration.
  - Load-bearing: selection skips symlinks and plain extensionless files while
    catching known script names and shebang files (behavior 6).
  - Load-bearing: non-UTF-8 tracked files are skipped with a stderr notice.
  - Load-bearing: invalid config files are rejected with exit code 2 (behavior 4).
  - Load-bearing: usage, repository, and state-file errors exit 2.
  - Load-bearing: state writes create parent directories and leave no temp file
    behind (behavior 16).

Run with:
    python3 -m pytest llm_file_size_guard_test.py
or:
    python3 llm_file_size_guard_test.py
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import llm_file_size_guard as guard  # noqa: E402


def run_git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )


def write_repeated_lines(path: Path, count: int, line: str = "value = 1") -> None:
    path.write_text("".join(f"{line}  # {idx}\n" for idx in range(count)), encoding="utf-8")


class TestLlmFileSizeGuard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        subprocess.run(
            ["git", "init", str(self.repo)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        self.state = self.repo / "guard_state.json"

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, *paths: Path) -> None:
        run_git(self.repo, "add", "--", *(str(path.relative_to(self.repo)) for path in paths))

    def run_guard(self, *args: str, use_config: bool = False, use_state: bool = True) -> tuple[int, str, str]:
        guard_args = ["--repo", str(self.repo)]
        if use_state:
            guard_args.extend(["--state", str(self.state)])
        if not use_config:
            guard_args.append("--no-config")
        guard_args.extend(args)
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            rc = guard.main(guard_args)
        return rc, stdout.getvalue(), stderr.getvalue()

    def test_check_reports_tracked_line_word_and_character_findings(self):
        # Load-bearing: line, word, and character thresholds all produce findings.
        line_warning = self.repo / "line_warning.py"
        word_warning = self.repo / "word_warning.md"
        char_error = self.repo / "char_error.py"
        untracked_error = self.repo / "untracked.py"
        write_repeated_lines(line_warning, 501)
        word_warning.write_text(" ".join("word" for _ in range(5001)), encoding="utf-8")
        char_error.write_text("x" * 64001, encoding="utf-8")
        write_repeated_lines(untracked_error, 900)
        self.add(line_warning, word_warning, char_error)

        rc, stdout, stderr = self.run_guard("check")

        self.assertEqual(rc, 1)
        self.assertEqual(stderr, "")
        self.assertIn("WARNING: line_warning.py", stdout)
        self.assertIn("breaks: lines 501 > 500", stdout)
        self.assertIn("WARNING: word_warning.md", stdout)
        self.assertIn("words 5001 > 5000", stdout)
        self.assertIn("ERROR: char_error.py", stdout)
        self.assertIn("characters 64001 > 64000", stdout)
        self.assertNotIn("untracked.py", stdout)

    def test_defer_suppresses_warning_until_line_growth_exceeds_threshold(self):
        # Load-bearing: valid defers suppress only until more than 100 lines of growth.
        path = self.repo / "review_me.py"
        write_repeated_lines(path, 550)
        self.add(path)

        rc, stdout, _stderr = self.run_guard("check")
        self.assertEqual(rc, 0)
        self.assertIn("WARNING: review_me.py", stdout)

        rc, stdout, _stderr = self.run_guard("defer", "review_me.py", "--reason", "human-reviewed")
        self.assertEqual(rc, 0)
        self.assertIn("Deferred review_me.py", stdout)
        state = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertIn("review_me.py", state["deferred"])
        self.assertEqual(state["deferred"]["review_me.py"]["metrics"]["lines"], 550)

        rc, stdout, _stderr = self.run_guard("check")
        self.assertEqual(rc, 0)
        self.assertNotIn("WARNING: review_me.py", stdout)
        self.assertIn("Suppressed 1 deferred warning", stdout)

        write_repeated_lines(path, 650)
        rc, stdout, _stderr = self.run_guard("check")
        self.assertEqual(rc, 0)
        self.assertNotIn("WARNING: review_me.py", stdout)

        write_repeated_lines(path, 651)
        rc, stdout, _stderr = self.run_guard("check")
        self.assertEqual(rc, 0)
        self.assertIn("WARNING: review_me.py", stdout)

    def test_repo_config_sets_thresholds_and_central_state_path(self):
        # Load-bearing: layered TOML config can set thresholds and central state location.
        path = self.repo / "configured.py"
        write_repeated_lines(path, 11)
        self.add(path)
        (self.repo / ".llm-file-size-guard.toml").write_text(
            """
[thresholds]
warn_lines = 10
fail_lines = 20

[tracking]
local_state_dir = "central-state"
""".strip()
            + "\n",
            encoding="utf-8",
        )

        rc, stdout, _stderr = self.run_guard("check", use_config=True, use_state=False)
        self.assertEqual(rc, 0)
        self.assertIn("WARNING: configured.py", stdout)
        self.assertIn("lines 11 > 10", stdout)

        rc, stdout, _stderr = self.run_guard("defer", "configured.py", use_config=True, use_state=False)
        self.assertEqual(rc, 0)
        self.assertIn("Deferred configured.py", stdout)
        state_files = list((self.repo / "central-state" / "repos").glob("*.json"))
        self.assertEqual(len(state_files), 1)
        state = json.loads(state_files[0].read_text(encoding="utf-8"))
        self.assertEqual(state["version"], 1)
        self.assertIn("key", state["repo"])
        self.assertIn("configured.py", state["deferred"])

        rc, stdout, _stderr = self.run_guard("check", use_config=True, use_state=False)
        self.assertEqual(rc, 0)
        self.assertNotIn("WARNING: configured.py", stdout)
        self.assertIn("Suppressed 1 deferred warning", stdout)

    def test_defer_reappears_after_character_growth_corollary(self):
        # Load-bearing: character growth corollary prevents dense one-line growth from hiding.
        path = self.repo / "dense_prompt.md"
        path.write_text("x" * 40001, encoding="utf-8")
        self.add(path)

        rc, stdout, _stderr = self.run_guard("defer", "dense_prompt.md")
        self.assertEqual(rc, 0)
        self.assertIn("Deferred dense_prompt.md", stdout)

        path.write_text("x" * 48001, encoding="utf-8")
        rc, stdout, _stderr = self.run_guard("check")
        self.assertEqual(rc, 0)
        self.assertNotIn("WARNING: dense_prompt.md", stdout)

        path.write_text("x" * 48002, encoding="utf-8")
        rc, stdout, _stderr = self.run_guard("check")
        self.assertEqual(rc, 0)
        self.assertIn("WARNING: dense_prompt.md", stdout)

    def test_expired_defer_and_hard_limit_are_not_deferred(self):
        # Load-bearing: age expiry and hard-limit failures override defers.
        path = self.repo / "aging.py"
        write_repeated_lines(path, 550)
        self.add(path)
        self.assertEqual(self.run_guard("defer", "aging.py")[0], 0)

        state = json.loads(self.state.read_text(encoding="utf-8"))
        state["deferred"]["aging.py"]["deferred_at"] = "2000-01-01T00:00:00Z"
        self.state.write_text(json.dumps(state), encoding="utf-8")
        rc, stdout, _stderr = self.run_guard("check")
        self.assertEqual(rc, 0)
        self.assertIn("WARNING: aging.py", stdout)

        self.assertEqual(self.run_guard("defer", "aging.py")[0], 0)
        write_repeated_lines(path, 801)
        rc, stdout, _stderr = self.run_guard("check")
        self.assertEqual(rc, 1)
        self.assertIn("ERROR: aging.py", stdout)

        rc, stdout, _stderr = self.run_guard("defer", "aging.py")
        self.assertEqual(rc, 1)
        self.assertIn("Cannot defer aging.py: exceeds hard-split threshold", stdout)

    def test_accept_suppresses_hard_limit_until_hash_changes(self):
        # Load-bearing: accepted frozen files suppress errors only for the accepted hash.
        path = self.repo / "frozen_oracle.py"
        write_repeated_lines(path, 900)
        self.add(path)

        rc, stdout, _stderr = self.run_guard("check")
        self.assertEqual(rc, 1)
        self.assertIn("ERROR: frozen_oracle.py", stdout)

        rc, stdout, _stderr = self.run_guard("accept", "frozen_oracle.py", "--reason", "campaign complete")
        self.assertEqual(rc, 0)
        self.assertIn("Accepted frozen_oracle.py", stdout)
        state = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertIn("frozen_oracle.py", state["accepted"])

        rc, stdout, _stderr = self.run_guard("check")
        self.assertEqual(rc, 0)
        self.assertNotIn("ERROR: frozen_oracle.py", stdout)
        self.assertIn("Suppressed 1 accepted file", stdout)

        write_repeated_lines(path, 901)
        rc, stdout, _stderr = self.run_guard("check")
        self.assertEqual(rc, 1)
        self.assertIn("ERROR: frozen_oracle.py", stdout)
        self.assertIn("accepted hash changed", stdout)

    def test_clear_removes_deferred_or_accepted_state(self):
        # Load-bearing: clear is the simple escape hatch for either state bucket.
        deferred = self.repo / "deferred.py"
        accepted = self.repo / "accepted.py"
        write_repeated_lines(deferred, 550)
        write_repeated_lines(accepted, 900)
        self.add(deferred, accepted)
        self.assertEqual(self.run_guard("defer", "deferred.py")[0], 0)
        self.assertEqual(self.run_guard("accept", "accepted.py")[0], 0)

        rc, stdout, _stderr = self.run_guard("clear", "deferred.py", "accepted.py", "missing.py")

        self.assertEqual(rc, 0)
        self.assertIn("Cleared deferred.py", stdout)
        self.assertIn("Cleared accepted.py", stdout)
        self.assertIn("No state for missing.py", stdout)
        state = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(state["deferred"], {})
        self.assertEqual(state["accepted"], {})

    def test_config_show_reports_effective_configuration(self):
        # Load-bearing: config show reports the effective merged configuration.
        (self.repo / ".llm-file-size-guard.toml").write_text(
            """
[thresholds]
warn_lines = 12
fail_lines = 30
words_per_line = 9
chars_per_line = 70
growth_lines = 5
defer_days = 3

[selection]
extensions = ["py", "md"]

[tracking]
local_state_dir = "central-state"
""".strip()
            + "\n",
            encoding="utf-8",
        )

        rc, stdout, stderr = self.run_guard(
            "config",
            "show",
            "--effective",
            use_config=True,
            use_state=False,
        )

        self.assertEqual(rc, 0)
        self.assertEqual(stderr, "")
        report = json.loads(stdout)
        self.assertEqual(report["thresholds"]["warn_lines"], 12)
        self.assertEqual(report["thresholds"]["fail_lines"], 30)
        self.assertEqual(report["thresholds"]["words_per_line"], 9)
        self.assertEqual(report["thresholds"]["chars_per_line"], 70)
        self.assertEqual(report["thresholds"]["growth_lines"], 5)
        self.assertEqual(report["thresholds"]["defer_days"], 3)
        self.assertEqual(report["selection"]["extensions"], [".md", ".py"])
        self.assertEqual(report["tracking"]["schema_version"], 1)
        self.assertIn("/central-state/repos/", report["tracking"]["state_path"])
        self.assertIn(str((self.repo / ".llm-file-size-guard.toml").resolve()), report["config"]["loaded"])


    def run_guard_raw(self, *args: str) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            rc = guard.main(list(args))
        return rc, stdout.getvalue(), stderr.getvalue()

    def test_selection_skips_symlinks_and_detects_shebangs_and_known_names(self):
        # Load-bearing: contract behavior 6 - maintained text selection.
        big = self.repo / "big_target.py"
        write_repeated_lines(big, 900)
        symlink = self.repo / "alias_link.py"
        symlink.symlink_to(big.name)
        makefile = self.repo / "Makefile"
        write_repeated_lines(makefile, 501)
        shebang_tool = self.repo / "deploytool"
        shebang_tool.write_text("#!/bin/sh\n" + "echo run\n" * 501, encoding="utf-8")
        plain_extensionless = self.repo / "plainnotes"
        plain_extensionless.write_text("word\n" * 900, encoding="utf-8")
        self.add(big, symlink, makefile, shebang_tool, plain_extensionless)

        rc, stdout, _stderr = self.run_guard("check")

        self.assertEqual(rc, 1)
        self.assertIn("ERROR: big_target.py", stdout)
        self.assertNotIn("alias_link.py", stdout)
        self.assertIn("WARNING: Makefile", stdout)
        self.assertIn("WARNING: deploytool", stdout)
        self.assertNotIn("plainnotes", stdout)

    def test_non_utf8_tracked_file_is_skipped_with_stderr_notice(self):
        # Load-bearing: unreadable tracked files produce a stderr notice, not a crash.
        bad = self.repo / "binary_blob.py"
        bad.write_bytes(b"\xff\xfe" + b"\x00" * 100)
        self.add(bad)

        rc, stdout, stderr = self.run_guard("check")

        self.assertEqual(rc, 0)
        self.assertIn("Skipped binary_blob.py: not UTF-8 text", stderr)
        self.assertNotIn("binary_blob.py", stdout)

    def test_config_validation_rejects_invalid_config_files(self):
        # Load-bearing: contract behavior 4 - config validation errors exit 2.
        config_path = self.repo / ".llm-file-size-guard.toml"
        cases = [
            ("not [valid toml", "not valid TOML"),
            ("[surprise]\nvalue = 1\n", "unsupported section"),
            ("[thresholds]\nwarn_lines = 0\n", "must be a positive integer"),
            ("[thresholds]\nmystery = 5\n", "unsupported threshold"),
            ("[selection]\nextensions = 5\n", "must be a string or list of strings"),
            ("[tracking]\nlocal_state_dir = 5\n", "must be a non-empty string"),
        ]
        for content, fragment in cases:
            with self.subTest(fragment=fragment):
                config_path.write_text(content, encoding="utf-8")
                rc, _stdout, stderr = self.run_guard("check", use_config=True)
                self.assertEqual(rc, 2)
                self.assertIn("Error:", stderr)
                self.assertIn(fragment, stderr)

    def test_usage_repo_and_state_errors_return_exit_code_2(self):
        # Load-bearing: usage, repository, and state-file errors exit 2 on stderr.
        with tempfile.TemporaryDirectory() as non_repo:
            rc, _stdout, stderr = self.run_guard_raw("--repo", non_repo, "--no-config", "check")
            self.assertEqual(rc, 2)
            self.assertIn("Error:", stderr)

        rc, _stdout, stderr = self.run_guard("check", "--warn-lines", "500", "--fail-lines", "500")
        self.assertEqual(rc, 2)
        self.assertIn("--fail-lines must be greater than --warn-lines", stderr)

        self.state.write_text("{not json", encoding="utf-8")
        rc, _stdout, stderr = self.run_guard("check")
        self.assertEqual(rc, 2)
        self.assertIn("not valid JSON", stderr)

        self.state.write_text(
            json.dumps({"version": 99, "repo": {}, "deferred": {}, "accepted": {}}),
            encoding="utf-8",
        )
        rc, _stdout, stderr = self.run_guard("check")
        self.assertEqual(rc, 2)
        self.assertIn("unsupported schema version", stderr)

        self.state.write_text(
            json.dumps({"version": 1, "repo": {"key": "someone-else"}, "deferred": {}, "accepted": {}}),
            encoding="utf-8",
        )
        rc, _stdout, stderr = self.run_guard("check")
        self.assertEqual(rc, 2)
        self.assertIn("different repository key", stderr)

    def test_state_write_creates_parents_and_leaves_no_temp_file(self):
        # Load-bearing: contract behavior 16 - atomic state writing.
        path = self.repo / "review_me.py"
        write_repeated_lines(path, 550)
        self.add(path)
        self.state = self.repo / "nested" / "dirs" / "guard_state.json"

        rc, _stdout, _stderr = self.run_guard("defer", "review_me.py")

        self.assertEqual(rc, 0)
        self.assertTrue(self.state.is_file())
        self.assertEqual(list(self.state.parent.glob("*.tmp")), [])
        state = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertIn("review_me.py", state["deferred"])


if __name__ == "__main__":
    unittest.main()
