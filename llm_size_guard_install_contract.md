Contract version: v1

# LLM Size Guard Install - zero-infrastructure installer and repo integrator: Contract

`llm_size_guard_install.sh` installs the `llm-size-guard` CLI directly from its
Git source URL (no package registry required) and wires the guard into other
repositories in the two supported integration shapes: a Git `pre-commit` hook
and a `size-guard` Makefile target. Each integration it writes carries a
management marker so re-runs are idempotent and unmanaged operator files are
never overwritten.

## Inputs

- **`tool` subcommand** - required command mode (one of `tool`, `hook`,
  `make-target`). Operator-provided, trusted. Installs the `llm-size-guard`
  CLI from a Git URL.
- **`tool --url URL`** - optional pip-style requirement URL. Operator-provided,
  trusted. Default:
  `git+ssh://git@github.com/bryant-quist-vgs/llm_file_size_guard.git`.
- **`tool --ref REF`** - optional Git branch, tag, or commit. Operator-provided,
  trusted. Appended to the URL as `@REF` when present.
- **`tool --installer NAME`** - optional installer choice: `auto` (default),
  `pipx`, `uv`, or `pip`. Operator-provided, trusted. `auto` picks the first
  available of `pipx`, `uv`, `python3 -m pip`.
- **`hook` subcommand** - required command mode. Operator-provided, trusted.
  Installs a managed Git pre-commit hook into a target repository.
- **`make-target` subcommand** - required command mode. Operator-provided,
  trusted. Adds a managed `size-guard` target to the target repository's
  `Makefile`, creating the `Makefile` when absent.
- **`hook|make-target --repo PATH`** - optional path to the target repository
  or a path inside it. Operator-provided, trusted. Defaults to the current
  directory.
- **`-h`/`--help`/`help`** - optional. Prints usage to stdout and exits 0.
- **Existing target-repo files** - `Makefile` at the repository root and the
  `pre-commit` file in the repository's Git hooks directory are read to decide
  whether they are managed by this script (contain the management marker),
  absent, or foreign. Operator-owned content, treated as untrusted: foreign
  content is never modified.

## Outputs

- **stdout** - progress and result messages naming the installer used, the hook
  path written, or the Makefile updated; usage text for `help`.
- **stderr** - `Error: ...` messages for refusals and usage errors.
- **exit code** - `0` on success or an idempotent no-op; `1` when the script
  refuses to act (foreign pre-commit hook, unmanaged `size-guard` Makefile
  target, target path not a Git repository, installer command failed or none
  available); `2` for usage errors (unknown command, unknown or valueless
  option).
- **Git pre-commit hook file** - written by `hook` at the target repository's
  `git rev-parse --git-path hooks`/`pre-commit`, marked executable. Contains
  the management marker, exits `0` with a stderr notice when `llm-size-guard`
  is not on `PATH`, and otherwise runs `llm-size-guard check`.
  `Load-bearing: commits in integrated repositories are blocked only by unsuppressed hard-limit failures, and clones without the tool are never blocked.`
- **Makefile managed block** - written by `make-target` at the target
  repository root: the management marker comment, `.PHONY: size-guard`, and a
  `size-guard` target whose recipe is `llm-size-guard check`.
  `Load-bearing: operators and CI run 'make size-guard' in integrated repositories.`

## Behaviors

1. **Command dispatch.** Requires exactly one of `tool`, `hook`, `make-target`,
   or a help flag; anything else is a usage error (exit 2).
2. **Installer selection.** For `tool` with `--installer auto`, picks the first
   of `pipx`, `uv`, `python3` found on `PATH`; a forced installer is used as
   given. Exits `1` when no supported installer is available.
3. **Tool installation.** Builds the requirement spec from `--url` plus
   optional `@REF` and delegates to exactly one installer invocation:
   `pipx install --force SPEC`, `uv tool install --force SPEC`, or
   `python3 -m pip install --user --upgrade SPEC`. The `--force`/`--upgrade`
   forms make re-runs upgrade an existing install.
   `Load-bearing: this is the zero-infrastructure distribution path; no package registry is required.`
4. **Target repository resolution.** For `hook` and `make-target`, resolves the
   target with `git rev-parse` (`--git-path hooks` for hooks, relative results
   resolved against `--repo`; `--show-toplevel` for the Makefile). A `--repo`
   that is not inside a Git work tree is a refusal (exit 1).
5. **Managed hook install.** Writes the pre-commit hook file and marks it
   executable when the hook path is absent or the existing file contains the
   management marker (managed hooks are overwritten in place so re-runs pick up
   hook-body updates). Creates the hooks directory when missing.
   `Load-bearing: re-running the installer is the supported hook upgrade path.`
6. **Foreign hook refusal.** When an existing pre-commit hook lacks the
   management marker, refuses (exit 1) without modifying the file and tells the
   operator to add `llm-size-guard check` to their hook manually.
7. **Managed Makefile block.** When the `Makefile` already contains the
   management marker, succeeds without changes. When it defines a `size-guard`
   target without the marker, refuses (exit 1) without modifying the file.
   Otherwise appends the managed block, creating the `Makefile` when absent.

Any behavior the script performs that is not listed here is **undeclared** and
constitutes drift. The script must not perform undeclared behaviors. An
adversarial reviewer treats undeclared behaviors as suspect.

## Declared capability surface

- **Filesystem reads:** the target repository's `Makefile` and existing
  `pre-commit` hook file, only to check for the management marker and an
  existing `size-guard` target.
- **Filesystem writes:** the target repository's Git hooks directory (created
  if missing), the `pre-commit` file within it (plus `chmod +x`), and the
  `Makefile` at the target repository root. No other filesystem writes.
- **Network access:** none performed directly. The delegated installer
  (`pipx`, `uv`, or `pip`) fetches the Git URL over the network.
- **Subprocess invocation:** `git rev-parse` (`--git-path hooks`,
  `--show-toplevel`) against the target repository; exactly one of
  `pipx install --force`, `uv tool install --force`,
  `python3 -m pip install --user --upgrade`; `chmod +x` on the hook file;
  `command -v` lookups for installer detection.
- **Environment variables read:** none explicitly; `PATH` is used implicitly
  for command lookup.
- **Secrets handled:** no secrets handled. SSH authentication for the Git URL
  is delegated entirely to the operator's existing Git/SSH setup.
- **Privilege escalation:** no privilege escalation; never invokes `sudo` and
  installs to user scope only.

## Assumptions for operation

- Runtime: `bash >= 3.2` (macOS system bash is sufficient).
- Dependencies: `git` on `PATH`; at least one of `pipx`, `uv`, or
  `python3 -m pip` on `PATH` for the `tool` command.
- Network: the machine can reach the Git host over SSH (or the scheme in
  `--url`) when installing the tool.
- The installed tool itself requires Python >= 3.11, per the main
  `llm_file_size_guard_contract.md`.
- Target repositories are ordinary Git work trees; hooks-path indirection is
  honored via `git rev-parse --git-path hooks`.
- Encoding: hook and Makefile content is ASCII.

## Anti-patterns this script must not do

- Do **not** overwrite or append to a pre-commit hook that lacks the
  management marker. Operator hook content is not this script's to edit.
- Do **not** modify an unmanaged `size-guard` Makefile target.
- Do **not** install with `sudo` or write outside the target repository.
- Do **not** write a hook that blocks commits when `llm-size-guard` is not
  installed; missing-tool is a notice, not a failure.
- Do **not** embed or handle credentials; authentication belongs to the
  operator's Git/SSH configuration.

## Revision rules

- Removing a behavior, an input, an output, or an assumption requires a high
  threshold and a deliberate version bump. Removals are recheck signals for
  everything that depends on the script.
- Added assumptions never relax previous assumptions.
- Added capabilities to the declared capability surface require operator
  review; a maintenance session that adds a capability silently is producing
  drift.
- The script's file header references the contract version it was built
  against.
