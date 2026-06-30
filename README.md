# LLM File Size Guard

Guards Git-tracked code and docs against LLM-unfriendly growth, supporting temporary deferrals and hash-locked acceptances for frozen artifacts safely over time.

`llm_file_size_guard.py` scans Git-tracked code, scripts, configuration, Markdown, and prompt-like text files for size patterns that are difficult for LLMs to maintain. It checks line count, word count, and character count together so files cannot avoid the guard by becoming denser and less readable.

The default heuristic is:

| Level | Lines | Words | Characters | Meaning |
| --- | ---: | ---: | ---: | --- |
| Warning | 500 | 5,000 | 40,000 | Evaluate whether this active file should be refactored. |
| Error | 800 | 8,000 | 64,000 | Split or explicitly accept the file as frozen historical content. |
| Growth wake-up | 100 | 1,000 | 8,000 | Revisit a deferred warning after meaningful growth. |

## Why This Exists

LLMs tend to struggle when individual source files grow too large. A simple line-count limit helps, but it is easy to game by compressing code, removing whitespace, or cramming more logic into fewer lines. This tool links line, word, and character thresholds so readability remains part of the pressure.

It also handles two legitimate exceptions:

- Active files can be temporarily deferred after human review.
- Frozen historical files can be accepted by hash, then wake up automatically if their content changes.

## Requirements

- Python 3.11 or newer
- Git available on `PATH`
- A Git work tree to scan

The tool uses only the Python standard library.

## Files

Copy these files into the target repository:

```text
llm_file_size_guard.py
llm_file_size_guard_commands.py
llm_file_size_guard_core.py
llm_file_size_guard_contract.md
llm_file_size_guard_test.py
```

Recommended `.gitignore` entry:

```gitignore
.llm_file_size_guard_state.json
```

## Quick Start

Run the guard from anywhere inside a Git repository:

```bash
python3 llm_file_size_guard.py check
```

Run the tests:

```bash
python3 -m pytest llm_file_size_guard_test.py
```

## Commands

### `check`

Scans Git-tracked maintained text files and prints any unsuppressed findings.

```bash
python3 llm_file_size_guard.py check
```

Warnings return exit code `0`; unsuppressed errors return exit code `1`.

### `defer`

Temporarily suppresses a warning-level finding for an active file.

```bash
python3 llm_file_size_guard.py defer path/to/file.py --reason "reviewed; refactor later"
```

A deferred warning wakes up when any of these happen:

- More than `--defer-days` days pass, default `7`.
- The file grows by more than the growth threshold, default `100` line equivalents.
- The file crosses the hard error threshold.

`defer` cannot suppress hard-limit errors. Use `accept` only when the file is genuinely frozen.

### `accept`

Suppresses an oversized file by exact SHA-256 hash. This is for completed artifacts that are no longer expected to change.

```bash
python3 llm_file_size_guard.py accept aggregate_evals/defects.1/eval_1/defects1_oracle.py \
  --reason "completed campaign oracle"
```

Accepted files can be warning-level or error-level. If the file content changes, `check` reports it again with an accepted-hash-changed note.

### `clear`

Removes either deferred or accepted state for a path.

```bash
python3 llm_file_size_guard.py clear path/to/file.py
```

`clear` is idempotent. It returns success even when the file had no stored state.

## Options

```bash
--repo PATH             Repository path, or a path inside it. Defaults to current directory.
--state PATH            Guard state path. Defaults to .llm_file_size_guard_state.json.
--warn-lines N          Warning line threshold. Default: 500.
--fail-lines N          Error line threshold. Default: 800.
--words-per-line N      Word-count multiplier. Default: 10.
--chars-per-line N      Character-count multiplier. Default: 80.
--growth-lines N        Deferred-growth threshold. Default: 100.
--defer-days N          Deferred-warning age limit. Default: 7.
--extensions CSV        Override the default maintained-text extension list.
```

Thresholds are linked. For example, `--warn-lines 600 --words-per-line 10 --chars-per-line 80` produces warning limits of 600 lines, 6,000 words, and 48,000 characters.

## State Model

The default state file is `.llm_file_size_guard_state.json`.

It has two main buckets:

- `deferred`: temporary warning suppressions for active files.
- `accepted`: exact-hash suppressions for frozen files.

State is stored by repository-relative POSIX path. The tool writes state atomically through a sibling temporary file, then replaces the target state file.

## Exit Codes

| Code | Meaning |
| ---: | --- |
| 0 | Command succeeded; `check` found no unsuppressed hard-limit errors. |
| 1 | `check` found an unsuppressed hard-limit error, or a state command could not process a requested file. |
| 2 | Usage, repository, Git, or state-file error. |

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
      - run: python3 llm_file_size_guard.py check
```

For CI, commit an intentionally curated state file only if the team wants shared acceptances or deferrals. Otherwise keep the default state file ignored and use the guard as a reporting tool during local development.

## Suggested Workflow

1. Run `check`.
2. Split or refactor active files that exceed the error threshold.
3. Use `defer` for active warning-level files that have been reviewed but do not need immediate splitting.
4. Use `accept` for frozen historical artifacts that should wake up only if their hash changes.
5. Use `clear` when a file returns to active development or when a waiver is no longer appropriate.
