#!/usr/bin/env bash
# llm_size_guard_install.sh - zero-infrastructure installer and repo integrator for llm-size-guard.
# Built against contract v1 (llm_size_guard_install_contract.md).

set -euo pipefail

DEFAULT_URL="git+ssh://git@github.com/bryant-quist-vgs/llm_file_size_guard.git"
MARKER="managed-by: llm-size-guard-install"

usage() {
    cat <<'EOF'
Usage: llm_size_guard_install.sh COMMAND [options]

Commands:
  tool         Install the llm-size-guard CLI from its Git source URL.
                 --url URL          pip-style requirement URL
                                    (default: git+ssh://git@github.com/bryant-quist-vgs/llm_file_size_guard.git)
                 --ref REF          Git branch, tag, or commit to install
                 --installer NAME   auto | pipx | uv | pip (default: auto)
  hook         Install a managed Git pre-commit hook that runs 'llm-size-guard check'.
                 --repo PATH        target repository (default: current directory)
  make-target  Add a managed 'size-guard' Makefile target that runs 'llm-size-guard check'.
                 --repo PATH        target repository (default: current directory)

Exit codes: 0 success or idempotent no-op, 1 refusal or installer failure, 2 usage error.
EOF
}

die_usage() {
    echo "Error: $*" >&2
    usage >&2
    exit 2
}

die() {
    echo "Error: $*" >&2
    exit 1
}

cmd_tool() {
    local url="$DEFAULT_URL" ref="" installer="auto"
    while [ $# -gt 0 ]; do
        case "$1" in
            --url) [ $# -ge 2 ] || die_usage "--url requires a value"; url="$2"; shift 2 ;;
            --ref) [ $# -ge 2 ] || die_usage "--ref requires a value"; ref="$2"; shift 2 ;;
            --installer) [ $# -ge 2 ] || die_usage "--installer requires a value"; installer="$2"; shift 2 ;;
            *) die_usage "unknown option for tool: $1" ;;
        esac
    done

    local spec="$url"
    [ -n "$ref" ] && spec="${url}@${ref}"

    if [ "$installer" = "auto" ]; then
        if command -v pipx >/dev/null 2>&1; then
            installer="pipx"
        elif command -v uv >/dev/null 2>&1; then
            installer="uv"
        elif command -v python3 >/dev/null 2>&1; then
            installer="pip"
        else
            die "no supported installer found; install pipx, uv, or python3 first"
        fi
    fi

    case "$installer" in
        pipx) pipx install --force "$spec" || die "pipx install failed" ;;
        uv) uv tool install --force "$spec" || die "uv tool install failed" ;;
        pip) python3 -m pip install --user --upgrade "$spec" || die "pip install failed" ;;
        *) die_usage "unknown installer: $installer (expected auto, pipx, uv, or pip)" ;;
    esac
    echo "Installed llm-size-guard via $installer from $spec"
}

hook_body() {
    cat <<EOF
#!/bin/sh
# $MARKER
# Pre-commit hook: block commits only on unsuppressed hard-limit file size failures.
if ! command -v llm-size-guard >/dev/null 2>&1; then
    echo "llm-size-guard is not installed; skipping file size check." >&2
    exit 0
fi
llm-size-guard check
EOF
}

cmd_hook() {
    local repo="."
    while [ $# -gt 0 ]; do
        case "$1" in
            --repo) [ $# -ge 2 ] || die_usage "--repo requires a value"; repo="$2"; shift 2 ;;
            *) die_usage "unknown option for hook: $1" ;;
        esac
    done

    local hooks_dir
    if ! hooks_dir=$(git -C "$repo" rev-parse --git-path hooks 2>/dev/null); then
        die "not a Git repository: $repo"
    fi
    case "$hooks_dir" in
        /*) ;;
        *) hooks_dir="$repo/$hooks_dir" ;;
    esac

    local hook_file="$hooks_dir/pre-commit"
    if [ -e "$hook_file" ] && ! grep -qF "$MARKER" "$hook_file"; then
        die "existing pre-commit hook at $hook_file is not managed by this installer; add 'llm-size-guard check' to it manually"
    fi

    mkdir -p "$hooks_dir"
    hook_body > "$hook_file"
    chmod +x "$hook_file"
    echo "Installed managed pre-commit hook at $hook_file"
}

make_block() {
    cat <<EOF
# $MARKER
.PHONY: size-guard
size-guard:
	llm-size-guard check
EOF
}

cmd_make_target() {
    local repo="."
    while [ $# -gt 0 ]; do
        case "$1" in
            --repo) [ $# -ge 2 ] || die_usage "--repo requires a value"; repo="$2"; shift 2 ;;
            *) die_usage "unknown option for make-target: $1" ;;
        esac
    done

    local root
    if ! root=$(git -C "$repo" rev-parse --show-toplevel 2>/dev/null); then
        die "not a Git repository: $repo"
    fi

    local makefile="$root/Makefile"
    if [ -e "$makefile" ]; then
        if grep -qF "$MARKER" "$makefile"; then
            echo "Managed size-guard target already present in $makefile"
            return 0
        fi
        if grep -qE '^size-guard[[:space:]]*:' "$makefile"; then
            die "Makefile at $makefile already defines a size-guard target not managed by this installer"
        fi
        printf '\n' >> "$makefile"
        make_block >> "$makefile"
    else
        make_block > "$makefile"
    fi
    echo "Added managed size-guard target to $makefile"
}

main() {
    [ $# -ge 1 ] || die_usage "a command is required: tool, hook, or make-target"
    local cmd="$1"
    shift
    case "$cmd" in
        tool) cmd_tool "$@" ;;
        hook) cmd_hook "$@" ;;
        make-target) cmd_make_target "$@" ;;
        -h|--help|help) usage ;;
        *) die_usage "unknown command: $cmd" ;;
    esac
}

main "$@"
