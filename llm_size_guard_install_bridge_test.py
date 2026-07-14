#!/usr/bin/env python3
"""Pytest bridge that runs llm_size_guard_install_test.sh.

The bash file is the canonical test suite for llm_size_guard_install.sh (see
llm_size_guard_install_contract.md). This bridge lets `python3 -m pytest` run
the whole repository's tests with one command.
"""

from __future__ import annotations

from pathlib import Path
import subprocess

SCRIPT_DIR = Path(__file__).resolve().parent


def test_installer_shell_suite_passes():
    result = subprocess.run(
        ["bash", str(SCRIPT_DIR / "llm_size_guard_install_test.sh")],
        capture_output=True,
        text=True,
    )
    print(result.stdout.strip())
    assert "0 failure(s)" in result.stdout
    assert result.returncode == 0, (
        f"installer shell suite failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
