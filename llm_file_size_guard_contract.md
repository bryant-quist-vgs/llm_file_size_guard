Contract version: v2

# LLM File Size Guard — tracked file size heuristic checker: Contract

`llm_file_size_guard.py` is the CLI entry point for scanning Git-tracked,
LLM-maintained text artifacts in a repository and reporting files whose line,
word, or character counts exceed review or hard-split thresholds. It delegates
the implementation to sibling modules `llm_file_size_guard_core.py` and
`llm_file_size_guard_commands.py` and records local state for two human-reviewed
cases: temporary deferrals for active files and hash-locked acceptances for
frozen files that should stay quiet until their content changes.

## Inputs

- **`check` subcommand** — optional command mode. Operator-provided, trusted. When
  omitted, the script behaves as if `check` was provided.
- **`defer` subcommand** — optional command mode. Operator-provided, trusted.
  Records a temporary deferral for one or more currently warning-level files.
- **`accept` subcommand** — optional command mode. Operator-provided, trusted.
  Records a hash-locked acceptance for one or more currently oversized files,
  including files over the hard-split threshold.
- **`clear` subcommand** — optional command mode. Operator-provided, trusted.
  Removes deferral or acceptance state for one or more paths.
- **`--repo PATH`** — optional path. Operator-provided, trusted. Identifies the
  Git repository or a path inside it. Defaults to the current directory.
- **`--state PATH`** — optional path. Operator-provided, trusted. JSON guard
  state file. Relative paths resolve under the repository root. Defaults to
  `.llm_file_size_guard_state.json` at the repository root.
- **`--warn-lines N`** — optional positive integer; default `500`. Sets the
  review-warning line threshold.
- **`--fail-lines N`** — optional positive integer; default `800`. Sets the
  hard-split line threshold and must be greater than `--warn-lines`.
- **`--words-per-line N`** — optional positive integer; default `10`. Converts a
  line threshold into a word threshold, so the default 500/800 line thresholds
  correspond to 5,000/8,000 words.
- **`--chars-per-line N`** — optional positive integer; default `80`. Converts a
  line threshold into a character threshold, so the default 500/800 line thresholds
  correspond to 40,000/64,000 characters.
- **`--growth-lines N`** — optional positive integer; default `100`. Converts to
  word and character growth thresholds with the same heuristic multipliers.
- **`--defer-days N`** — optional positive integer; default `7`. Maximum age for
  a deferral before the warning reappears.
- **`--extensions CSV`** — optional comma-separated list of extensions.
  Operator-provided, trusted. Overrides the default maintained-text extension set.
  Extensions may be provided with or without a leading dot.
- **`defer FILE ...`** — required for the `defer` subcommand. Operator-provided,
  trusted paths interpreted relative to the repository root unless absolute.
- **`defer --reason TEXT`** — optional text. Operator-provided, trusted. Stored
  in the state file for human context.
- **`accept FILE ...`** — required for the `accept` subcommand.
  Operator-provided, trusted paths interpreted relative to the repository root
  unless absolute.
- **`accept --reason TEXT`** — optional text. Operator-provided, trusted. Stored
  in the state file for human context.
- **`clear FILE ...`** — required for the `clear` subcommand. Operator-provided,
  trusted paths interpreted relative to the repository root unless absolute.

## Outputs

- **stdout** — human-readable findings from `check`; human-readable state-change
  results from `defer`, `accept`, and `clear`. A finding names the path,
  severity, all current metrics, every metric that breaks the relevant
  threshold, and when applicable that an accepted hash changed.
  `Load-bearing: operators and CI logs need enough information to decide whether
  to refactor, split, defer, or accept a file.`
- **stderr** — usage errors and notices about skipped tracked files that cannot be
  read as maintained UTF-8 text.
- **exit code** — `0` when `check` finds no unsuppressed hard-limit failures,
  even if it prints review warnings; `1` when `check` finds any unsuppressed
  hard-limit failure or when `defer`/`accept` cannot record one or more
  requested files; `2` for usage or repository errors. `clear` returns `0` when
  it can read and update state, including when a requested path had no state.
- **`.llm_file_size_guard_state.json` or `--state PATH`** — JSON state written by
  `defer`, `accept`, and `clear`. Contains a schema version, `deferred` records,
  and `accepted` records. Records store per-path SHA-256 hash, timestamp,
  baseline metrics, thresholds, and optional reason.
  `Load-bearing: future checks use this state to suppress only still-valid
  deferrals or exact accepted file contents.`

## Behaviors

1. **Repository discovery.** Resolves `--repo` to the Git work-tree root with
   `git rev-parse --show-toplevel`, then enumerates tracked paths with
   `git ls-files -z`.
   `Load-bearing: the checker must not report untracked scratch files or ignored
   generated output.`
2. **Maintained text selection.** Checks tracked files with common code, script,
   configuration, Markdown, and prompt-document extensions; known extensionless
   script filenames; and files with a shebang. Tracked symlinks are skipped rather
   than followed.
3. **Metric counting.** Reads selected files as UTF-8, computes logical lines,
   non-whitespace word chunks, Unicode character count, and SHA-256 over the raw
   bytes.
   `Load-bearing: line, word, and character counts together discourage dense,
   less-readable compression to avoid line-count limits.`
4. **Threshold heuristic.** Converts line thresholds to word and character
   thresholds with `words = lines * --words-per-line` and
   `characters = lines * --chars-per-line`. Defaults are 500 lines / 5,000 words /
   40,000 characters for review warnings and 800 lines / 8,000 words / 64,000
   characters for hard-split failures.
   `Load-bearing: the word and character checks must remain tied to the line
   heuristic so threshold changes move together.`
5. **Finding classification.** A file is an `ERROR` if any metric exceeds the
   hard-split threshold, a `WARNING` if no hard threshold is broken but any review
   threshold is broken, and omitted otherwise.
   `Load-bearing: hard-limit failures should be usable as CI blockers while
   review warnings remain advisory.`
6. **Deferral suppression.** `check` suppresses only warning-level findings with a
   valid `deferred` state entry when all of these are true: the deferral age is
   not more than `--defer-days`; no metric has grown by more than the growth
   threshold since the deferral baseline; and the current file does not exceed
   any hard-split threshold. Hash changes alone do not re-enable a deferred
   warning, but the current hash is retained in state for auditability.
   `Load-bearing: humans can defer a known warning without hiding meaningful
   growth, expiry, or hard-limit failures.`
7. **Acceptance suppression.** `check` suppresses warning-level and hard-limit
   findings with a valid `accepted` state entry only when the current file hash
   exactly matches the accepted SHA-256 hash. If the hash differs and the file is
   still oversized, the finding is printed with a hash-change note.
   `Load-bearing: completed historical artifacts can be quiet indefinitely while
   automatically reappearing if they enter development again.`
8. **Deferral creation.** `defer` records state only for selected, tracked files
   that currently exceed a review threshold and do not exceed a hard-split
   threshold. It refuses to defer files below the review threshold, untracked
   paths, skipped file types, unreadable files, and hard-limit failures.
9. **Acceptance creation.** `accept` records state only for selected, tracked
   files that currently exceed a review or hard-split threshold. It refuses files
   below the review threshold, untracked paths, skipped file types, and unreadable
   files.
10. **State clearing.** `clear` removes any `deferred` or `accepted` state for
   each requested repository-relative path and reports when a path had no state.
11. **Legacy state normalization.** When reading an older state file containing
   a `snoozes` object, the script treats those records as `deferred` records in
   memory and writes the v2 shape on the next state-changing command.
12. **State writing.** Writes guard state atomically by creating parent
   directories as needed, writing a sibling temporary file, and replacing the
   target state path.
13. **Stable path keys.** Stores state by repository-relative POSIX path. Absolute
   `defer`, `accept`, and `clear` inputs must resolve inside the repository.

Any behavior the script performs that is not listed here is **undeclared** and
constitutes drift. The script must not perform undeclared behaviors. An
adversarial reviewer treats undeclared behaviors as suspect.

## Declared capability surface

- **Filesystem reads:** May read small prefixes of Git-tracked files for shebang
  detection, may read the repository working tree for selected Git-tracked files,
  and may read the configured guard state file.
- **Filesystem writes:** May write only the configured guard state file and a
  sibling temporary file used for atomic replacement.
- **Network access:** No network access.
- **Subprocess invocation:** Invokes the system `git` binary only with
  `rev-parse --show-toplevel` and `ls-files -z`.
- **Environment variables read:** No environment variables read.
- **Secrets handled:** No secrets handled.
- **Privilege escalation:** No privilege escalation.

## Assumptions for operation

- Runtime version: Python >= 3.11.
- Dependencies: Python standard library only.
- System requirements: `git` is installed and available on PATH.
- Encoding assumptions: selected maintained text files and JSON state are UTF-8.
- Filesystem assumptions: repository paths can be represented relative to the Git
  work-tree root with POSIX separators.
- Time assumptions: deferral and acceptance timestamps use UTC ISO-8601 values.

## Anti-patterns this script must not do

- Do **not** suppress hard-split failures because of a deferral.
- Do **not** suppress accepted files when the current SHA-256 differs from the
  accepted SHA-256.
- Do **not** inspect untracked or ignored files during `check`.
- Do **not** use line count as the only size signal.
- Do **not** follow tracked symlinks to read content outside the repository.
- Do **not** silently rewrite source files while checking or updating guard state.

## Revision rules

- Removing a behavior, an input, an output, or an assumption requires a high
  threshold and a deliberate version bump. Removals are recheck signals for
  everything that depends on the script.
- Added assumptions never relax previous assumptions.
- Added capabilities to the declared capability surface require operator review;
  a maintenance session that adds a capability silently is producing drift.
- The script's file header references the contract version it was built against.
