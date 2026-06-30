#!/usr/bin/env python3
"""llm_file_size_guard_test.py - Tests for llm_file_size_guard.py, built against contract v2.

Coverage:
  - Happy path: reports warning and hard-limit findings for tracked maintained files.
  - Load-bearing: line, word, and character thresholds all produce findings.
  - Load-bearing: untracked files are ignored.
  - Load-bearing: deferred warnings reappear after age, line, or character growth.
  - Load-bearing: accepted files suppress warnings and hard-limit errors only while the hash matches.
  - Load-bearing: clear removes either deferred or accepted state.

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

    def run_guard(self, *args: str) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            rc = guard.main(["--repo", str(self.repo), "--state", str(self.state), *args])
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


if __name__ == "__main__":
    unittest.main()
