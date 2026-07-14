Contract version: v2

# LLM File Size Guard - centralized file size heuristic checker: Contract

`llm_file_size_guard.py` is the CLI entry point for the installable
`llm-size-guard` command. It scans Git-tracked, LLM-maintained text artifacts in
a repository and reports files whose line, word, or character counts exceed
review or hard-split thresholds. It reads layered TOML configuration, stores
per-repository JSON state in a centralized user state directory by default, and
records two human-reviewed cases: temporary deferrals for active files and
hash-locked acceptances for frozen files that should stay quiet until their
content changes.

## Inputs

- **`check` subcommand** - optional command mode. Operator-provided, trusted.
  When omitted, the script behaves as if `check` was provided.
- **`defer` subcommand** - optional command mode. Operator-provided, trusted.
  Records a temporary deferral for one or more currently warning-level files.
- **`accept` subcommand** - optional command mode. Operator-provided, trusted.
  Records a hash-locked acceptance for one or more currently oversized files,
  including files over the hard-split threshold.
- **`clear` subcommand** - optional command mode. Operator-provided, trusted.
  Removes deferral or acceptance state for one or more paths.
- **`config show --effective` subcommand** - optional command mode.
  Operator-provided, trusted. Prints the merged effective configuration as JSON.
- **`--repo PATH`** - optional path. Operator-provided, trusted. Identifies the
  Git repository or a path inside it. Defaults to the current directory.
- **`--state PATH`** - optional path. Operator-provided, trusted. Exact JSON
  guard state file. Relative paths resolve under the repository root. When
  omitted, the script writes central per-repository state under the configured
  local state directory.
- **`--no-config`** - optional boolean. Operator-provided, trusted. Skips
  standard system, user, and repository config files.
- **`--warn-lines N`** - optional positive integer; default `500`. Sets the
  review-warning line threshold.
- **`--fail-lines N`** - optional positive integer; default `800`. Sets the
  hard-split line threshold and must be greater than `--warn-lines`.
- **`--words-per-line N`** - optional positive integer; default `10`. Converts a
  line threshold into a word threshold.
- **`--chars-per-line N`** - optional positive integer; default `80`. Converts a
  line threshold into a character threshold.
- **`--growth-lines N`** - optional positive integer; default `100`. Converts to
  word and character growth thresholds with the same heuristic multipliers.
- **`--defer-days N`** - optional positive integer; default `7`. Maximum age for
  a deferral before the warning reappears.
- **`--extensions CSV`** - optional comma-separated list of extensions.
  Operator-provided, trusted. Overrides the maintained-text extension set.
- **`--ignore-dirs CSV`** - optional comma-separated list of repository-relative
  directory paths. Operator-provided, trusted. Tracked files under any listed
  directory are excluded from scanning. Entries must be relative paths without
  parent-directory traversal; trailing slashes and leading `./` are normalized
  away. Overrides any configured ignored-directory list.
- **Standard TOML config files** - optional operator-managed files. The script
  reads these in order when not passed `--no-config`: system config,
  user config, and repository config `.llm-file-size-guard.toml`. Later files
  override earlier files.
- **Config `[thresholds]` table** - optional positive integer values matching
  the threshold CLI flags.
- **Config `[selection].extensions`** - optional string or list of strings.
  Overrides the maintained-text extension set.
- **Config `[selection].ignore_dirs`** - optional string or list of strings.
  Repository-relative directory paths whose tracked files are excluded from
  scanning, with the same semantics as `--ignore-dirs`.
- **Config `[tracking].local_state_dir`** - optional path string. Sets the
  directory that receives central per-repository state under `repos/`.
- **Config `[tracking].state_path`** - optional path string. Sets an exact JSON
  state path, equivalent to `--state`.
- **`defer FILE ...`** - required for the `defer` subcommand.
  Operator-provided, trusted paths interpreted relative to the repository root
  unless absolute.
- **`defer --reason TEXT`** - optional text. Operator-provided, trusted. Stored
  in the state file for human context.
- **`accept FILE ...`** - required for the `accept` subcommand.
  Operator-provided, trusted paths interpreted relative to the repository root
  unless absolute.
- **`accept --reason TEXT`** - optional text. Operator-provided, trusted. Stored
  in the state file for human context.
- **`clear FILE ...`** - required for the `clear` subcommand. Operator-provided,
  trusted paths interpreted relative to the repository root unless absolute.

## Outputs

- **stdout** - human-readable findings from `check`; human-readable state-change
  results from `defer`, `accept`, and `clear`; JSON effective configuration from
  `config show --effective`.
  `Load-bearing: operators and CI logs need enough information to decide whether to refactor, split, defer, accept, clear, or inspect active policy.`
- **stderr** - usage errors and notices about skipped tracked files that cannot
  be read as maintained UTF-8 text.
- **exit code** - `0` when a command succeeds and `check` finds no unsuppressed
  hard-limit failures; `1` when `check` finds any unsuppressed hard-limit
  failure or when `defer`/`accept` cannot record one or more requested files;
  `2` for usage, repository, Git, config, or state-file errors.
- **Central or explicit JSON state file** - written by `defer`, `accept`, and
  `clear`. Contains schema version `1`, repository identity metadata,
  `deferred` records, and `accepted` records.
  `Load-bearing: future checks use this state to suppress only still-valid deferrals or exact accepted file contents.`
- **Package metadata** - `pyproject.toml` exposes the console command
  `llm-size-guard`.
  `Load-bearing: centralized installation depends on the console script entry point.`

## Behaviors

1. **Repository discovery.** Resolves `--repo` to the Git work-tree root with
   `git rev-parse --show-toplevel`, then enumerates tracked paths with
   `git ls-files -z`.
   `Load-bearing: the checker must not report untracked scratch files or ignored generated output.`
2. **Repository identity.** Reads `remote.origin.url` with
   `git config --get remote.origin.url` when available. The central state key is
   the SHA-256 of `remote:<url>` when a remote exists, otherwise the SHA-256 of
   `path:<repo root>`.
   `Load-bearing: central state must remain per repository and stable across clones when an origin remote is available.`
3. **Layered config loading.** Unless `--no-config` is passed, reads standard
   config files in this order: system, user, repository. Later files override
   earlier files, and CLI flags override all config files.
   `Load-bearing: one centralized policy can be shared by default while a repository can still tighten local policy.`
4. **Config validation.** Rejects invalid TOML, unsupported config sections or
   fields, non-positive integer thresholds, invalid extension values, and
   invalid ignored-directory values (non-string entries, absolute paths, or
   parent-directory traversal).
5. **Central state resolution.** When no exact state path is provided, stores
   per-repository state in `<local_state_dir>/repos/<repo-key>.json`. On macOS,
   the default user support directory is
   `~/Library/Application Support/llm-file-size-guard`.
   `Load-bearing: the tool no longer requires a state file to live in each scanned repository.`
6. **Maintained text selection.** Checks tracked files with common code, script,
   configuration, Markdown, and prompt-document extensions; known extensionless
   script filenames; and files with a shebang. Tracked symlinks are skipped
   rather than followed. Tracked files whose repository-relative path lies under
   any configured ignored directory (matched on whole path components) are
   excluded from scanning silently, and `defer`/`accept` refuse them with an
   ignored-directory reason.
   `Load-bearing: repositories can quiet frequently changing directories that are never LLM-maintained without accepting or deferring each file.`
7. **Metric counting.** Reads selected files as UTF-8, computes logical lines,
   non-whitespace word chunks, Unicode character count, and SHA-256 over the raw
   bytes.
   `Load-bearing: line, word, and character counts together discourage dense, less-readable compression to avoid line-count limits.`
8. **Threshold heuristic.** Converts line thresholds to word and character
   thresholds with `words = lines * --words-per-line` and
   `characters = lines * --chars-per-line`.
   `Load-bearing: the word and character checks must remain tied to the line heuristic so threshold changes move together.`
9. **Finding classification.** A file is an `ERROR` if any metric exceeds the
   hard-split threshold, a `WARNING` if no hard threshold is broken but any
   review threshold is broken, and omitted otherwise.
   `Load-bearing: hard-limit failures should be usable as CI blockers while review warnings remain advisory.`
10. **Deferral suppression.** `check` suppresses only warning-level findings
    with a valid `deferred` state entry when the deferral age is not more than
    `--defer-days`, no metric has grown by more than the growth threshold since
    the deferral baseline, and the current file does not exceed any hard-split
    threshold.
    `Load-bearing: humans can defer a known warning without hiding meaningful growth, expiry, or hard-limit failures.`
11. **Acceptance suppression.** `check` suppresses warning-level and hard-limit
    findings with a valid `accepted` state entry only when the current file hash
    exactly matches the accepted SHA-256 hash. If the hash differs and the file
    is still oversized, the finding is printed with a hash-change note.
    `Load-bearing: completed historical artifacts can be quiet indefinitely while automatically reappearing if they enter development again.`
12. **Deferral creation.** `defer` records state only for selected, tracked files
    that currently exceed a review threshold and do not exceed a hard-split
    threshold. It refuses files below the review threshold, untracked paths,
    skipped file types, unreadable files, and hard-limit failures.
13. **Acceptance creation.** `accept` records state only for selected, tracked
    files that currently exceed a review or hard-split threshold. It refuses
    files below the review threshold, untracked paths, skipped file types, and
    unreadable files.
14. **State clearing.** `clear` removes any `deferred` or `accepted` state for
    each requested repository-relative path and reports when a path had no state.
15. **State schema.** State files use schema version `1`, include repository
    identity metadata, and store state by repository-relative POSIX path.
    `Load-bearing: state must be auditable outside a single repository checkout.`
16. **State writing.** Writes guard state atomically by creating parent
    directories as needed, writing a sibling temporary file, and replacing the
    target state path.
17. **Config inspection.** `config show --effective` prints JSON containing the
    command name, repository root, repository identity, loaded and candidate
    config files, thresholds, selected extensions, ignored directories, state
    schema version, local state directory, and resolved state path.
    `Load-bearing: operators need to see the active centralized policy without scanning or mutating files.`

Any behavior the script performs that is not listed here is **undeclared** and
constitutes drift. The script must not perform undeclared behaviors. An
adversarial reviewer treats undeclared behaviors as suspect.

## Declared capability surface

- **Filesystem reads:** May read standard config files, the repository config
  file, small prefixes of Git-tracked files for shebang detection, selected
  Git-tracked maintained text files, and the configured guard state file.
- **Filesystem writes:** May write only the configured guard state file and a
  sibling temporary file used for atomic replacement.
- **Network access:** No network access.
- **Subprocess invocation:** Invokes the system `git` binary only with
  `rev-parse --show-toplevel`, `ls-files -z`, and
  `config --get remote.origin.url`.
- **Environment variables read:** No explicit environment variables read.
  Platform home-directory resolution is delegated to Python standard library
  path helpers.
- **Secrets handled:** No secrets handled.
- **Privilege escalation:** No privilege escalation.

## Assumptions for operation

- Runtime version: Python >= 3.11.
- Dependencies: Python standard library only.
- System requirements: `git` is installed and available on PATH.
- Encoding assumptions: selected maintained text files, TOML config files, and
  JSON state are UTF-8.
- Filesystem assumptions: repository paths can be represented relative to the
  Git work-tree root with POSIX separators.
- Platform assumptions: macOS is the primary operating environment; Linux and
  Windows path defaults are best-effort and isolated behind platform path
  helpers.
- Time assumptions: deferral and acceptance timestamps use UTC ISO-8601 values.
- Tracking assumptions: collaborative/shared exception tracking is outside this
  contract and belongs to future work.

## Anti-patterns this script must not do

- Do **not** suppress hard-split failures because of a deferral.
- Do **not** suppress accepted files when the current SHA-256 differs from the
  accepted SHA-256.
- Do **not** inspect untracked or ignored files during `check`.
- Do **not** use line count as the only size signal.
- Do **not** follow tracked symlinks to read content outside the repository.
- Do **not** silently rewrite source files while checking or updating guard
  state.
- Do **not** perform network synchronization for collaborative tracking.

## Revision rules

- Removing a behavior, an input, an output, or an assumption requires a high
  threshold and a deliberate version bump. Removals are recheck signals for
  everything that depends on the script.
- Added assumptions never relax previous assumptions.
- Added capabilities to the declared capability surface require operator review;
  a maintenance session that adds a capability silently is producing drift.
- The script's file header references the contract version it was built against.
