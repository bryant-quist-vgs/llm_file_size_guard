# LLM File Size Guard

Centralized guard for Git-tracked code and docs that are getting too large for
LLM-assisted maintenance. It checks line count, word count, and character count
together so files cannot avoid the guard by becoming denser and less readable.

The installed command is:

```bash
llm-size-guard
```

The default heuristic is:

| Level | Lines | Words | Characters | Meaning |
| --- | ---: | ---: | ---: | --- |
| Warning | 500 | 5,000 | 40,000 | Evaluate whether this active file should be refactored. |
| Error | 800 | 8,000 | 64,000 | Split or explicitly accept the file as frozen historical content. |
| Growth wake-up | 100 | 1,000 | 8,000 | Revisit a deferred warning after meaningful growth. |

## Requirements

- Python 3.11 or newer
- Git available on `PATH`
- A Git work tree to scan

The tool uses only the Python standard library.

## Install

From this repository:

```bash
python3 -m pip install .
```

For a user-local install that exposes the command globally, use `pipx`:

```bash
pipx install .
```

An internal Homebrew formula can wrap the same package for macOS team use. The
package entry point is declared in `pyproject.toml` as `llm-size-guard`.

### Zero-infrastructure install script

`llm_size_guard_install.sh` installs the CLI straight from the Git source URL —
no package registry required — and wires the guard into other repositories as a
pre-commit hook or a make target:

```bash
# Install the CLI (auto-selects pipx, uv, or pip --user):
bash llm_size_guard_install.sh tool

# Pin a branch or tag, or point at a fork:
bash llm_size_guard_install.sh tool --ref main
bash llm_size_guard_install.sh tool --url git+ssh://git@github.com/you/llm_file_size_guard.git

# Add a managed pre-commit hook to another repository:
bash llm_size_guard_install.sh hook --repo ~/src/other-project

# Add a managed 'make size-guard' target to another repository:
bash llm_size_guard_install.sh make-target --repo ~/src/other-project
```

The hook blocks commits only on unsuppressed hard-limit failures and skips
quietly when `llm-size-guard` is not installed, so clones without the tool are
never blocked. Both integrations carry a `managed-by: llm-size-guard-install`
marker: re-running the installer updates them in place, and existing hooks or
`size-guard` targets without the marker are refused rather than modified. See
`llm_size_guard_install_contract.md` for the full behavior contract.

## Quick Start

Run from anywhere inside a Git repository:

```bash
llm-size-guard check
```

Warnings return exit code `0`; unsuppressed errors return exit code `1`.

Inspect the merged effective config:

```bash
llm-size-guard config show --effective
```

Run all tests from this source repository (the guard's suite plus the install
script's shell suite):

```bash
python3 -m pytest
```

## Configuration

Configuration is layered. Later layers override earlier layers, and CLI flags
override all config files.

1. Built-in defaults
2. System config: `/Library/Application Support/llm-file-size-guard/config.toml`
3. User config: `~/Library/Application Support/llm-file-size-guard/config.toml`
4. Repository config: `.llm-file-size-guard.toml`
5. CLI flags

Example:

```toml
[thresholds]
warn_lines = 500
fail_lines = 800
words_per_line = 10
chars_per_line = 80
growth_lines = 100
defer_days = 7

[selection]
extensions = ["py", "ts", "tsx", "md", "yaml", "json"]

[tracking]
local_state_dir = "~/Library/Application Support/llm-file-size-guard/state"
```

Use `--no-config` to ignore all config files for a single invocation.

## Central State

By default, state is no longer written into the scanned repository. It is stored
per repository under:

```text
~/Library/Application Support/llm-file-size-guard/state/repos/<repo-key>.json
```

The repo key is based on `remote.origin.url` when available, or the repository
root path when no origin remote exists. State files use schema version `1` and
include repository identity metadata.

Use `--state PATH` or `[tracking].state_path` only when you need an exact state
file path for a special run.

## Commands

### `check`

Scans Git-tracked maintained text files and prints any unsuppressed findings.

```bash
llm-size-guard check
```

### `defer`

Temporarily suppresses a warning-level finding for an active file.

```bash
llm-size-guard defer path/to/file.py --reason "reviewed; refactor later"
```

A deferred warning wakes up when any of these happen:

- More than `--defer-days` days pass, default `7`.
- The file grows by more than the growth threshold, default `100` line equivalents.
- The file crosses the hard error threshold.

`defer` cannot suppress hard-limit errors. Use `accept` only when the file is
genuinely frozen.

### `accept`

Suppresses an oversized file by exact SHA-256 hash. This is for completed
artifacts that are no longer expected to change.

```bash
llm-size-guard accept aggregate_evals/defects.1/eval_1/defects1_oracle.py \
  --reason "completed campaign oracle"
```

Accepted files can be warning-level or error-level. If the file content changes,
`check` reports it again with an accepted-hash-changed note.

### `clear`

Removes either deferred or accepted state for a path.

```bash
llm-size-guard clear path/to/file.py
```

`clear` is idempotent. It returns success even when the file had no stored state.

### `config show --effective`

Prints the merged effective policy and resolved state path as JSON.

```bash
llm-size-guard config show --effective
```

## Options

```bash
--repo PATH             Repository path, or a path inside it. Defaults to current directory.
--state PATH            Exact guard state path. Defaults to central per-repo state.
--no-config             Ignore system, user, and repository config files.
--warn-lines N          Warning line threshold. Default: 500.
--fail-lines N          Error line threshold. Default: 800.
--words-per-line N      Word-count multiplier. Default: 10.
--chars-per-line N      Character-count multiplier. Default: 80.
--growth-lines N        Deferred-growth threshold. Default: 100.
--defer-days N          Deferred-warning age limit. Default: 7.
--extensions CSV        Override the default maintained-text extension list.
```

Thresholds are linked. For example, `--warn-lines 600 --words-per-line 10
--chars-per-line 80` produces warning limits of 600 lines, 6,000 words, and
48,000 characters.

## CI Example

```yaml
name: file-size-guard

on:
  pull_request:

jobs:
  guard:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: python3 -m pip install .
      - run: llm-size-guard check --no-config
```

## Future Work

Collaborative/shared tracking of reviewed exceptions is intentionally not
implemented yet. A later version can add explicit sync or export commands for a
team-owned registry without changing normal local checks into networked
operations.
