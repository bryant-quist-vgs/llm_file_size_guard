#!/usr/bin/env bash
# llm_size_guard_install_test.sh - Tests for llm_size_guard_install.sh, built against contract v1.
#
# Coverage:
#   - Happy path: tool mode delegates to an installer with the default git URL spec.
#   - Load-bearing: zero-infrastructure install path (behavior 3) for pipx, uv, and pip,
#     including --url/--ref spec construction and auto installer selection (behavior 2).
#   - Load-bearing: hook mode writes an executable managed hook that runs
#     'llm-size-guard check' and tolerates a missing tool (behavior 5, hook output).
#   - Load-bearing: re-running hook install is the supported upgrade path (behavior 5).
#   - Trust boundary: foreign pre-commit hooks are refused unchanged (behavior 6).
#   - Load-bearing: make-target creates/appends the managed block with a tab recipe,
#     is idempotent, and refuses unmanaged size-guard targets (behavior 7).
#   - Edge cases: non-repo --repo refusal (behavior 4), unknown command/option usage
#     errors exit 2 (behavior 1).
#
# Run with:
#     bash llm_size_guard_install_test.sh

set -u

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
INSTALL="$SCRIPT_DIR/llm_size_guard_install.sh"
TAB=$(printf '\t')
TESTS=0
FAILURES=0
SANDBOXES=""

cleanup() {
    for dir in $SANDBOXES; do
        rm -rf "$dir"
    done
}
trap cleanup EXIT

sandbox() {
    local dir
    dir=$(mktemp -d "${TMPDIR:-/tmp}/lsg_install_test.XXXXXX")
    SANDBOXES="$SANDBOXES $dir"
    echo "$dir"
}

# Create a stub executable that records its invocation and succeeds.
make_stub() {
    local dir="$1" name="$2"
    cat > "$dir/$name" <<EOF
#!/bin/sh
echo "$name \$*" >> "$dir/calls.log"
exit 0
EOF
    chmod +x "$dir/$name"
}

fail() {
    FAILURES=$((FAILURES + 1))
    echo "FAIL: $CURRENT_TEST - $*" >&2
}

assert_eq() {
    [ "$1" = "$2" ] || fail "expected '$2', got '$1' ($3)"
}

assert_file_contains() {
    grep -qF "$2" "$1" || fail "expected $1 to contain '$2'"
}

assert_file_not_contains() {
    if [ -e "$1" ] && grep -qF "$2" "$1"; then
        fail "expected $1 not to contain '$2'"
    fi
}

run_test() {
    CURRENT_TEST="$1"
    TESTS=$((TESTS + 1))
    "$1"
}

git_repo() {
    local dir="$1"
    git init -q "$dir" >/dev/null 2>&1
}

test_tool_auto_prefers_pipx_with_default_url() {
    # Load-bearing: behaviors 2 and 3 - auto selection and delegated install.
    local box; box=$(sandbox)
    make_stub "$box" pipx
    PATH="$box:$PATH" bash "$INSTALL" tool >/dev/null 2>&1
    assert_eq "$?" 0 "tool exit code"
    assert_file_contains "$box/calls.log" \
        "pipx install --force git+ssh://git@github.com/bryant-quist-vgs/llm_file_size_guard.git"
}

test_tool_forced_uv_and_pip_installers() {
    # Load-bearing: behavior 3 - each installer gets its exact upgrade-capable form.
    local box; box=$(sandbox)
    make_stub "$box" uv
    make_stub "$box" python3
    PATH="$box:$PATH" bash "$INSTALL" tool --installer uv >/dev/null 2>&1
    assert_eq "$?" 0 "uv exit code"
    PATH="$box:$PATH" bash "$INSTALL" tool --installer pip >/dev/null 2>&1
    assert_eq "$?" 0 "pip exit code"
    assert_file_contains "$box/calls.log" "uv tool install --force git+ssh://"
    assert_file_contains "$box/calls.log" "python3 -m pip install --user --upgrade git+ssh://"
}

test_tool_url_and_ref_build_spec() {
    # Load-bearing: behavior 3 - spec is URL plus @REF.
    local box; box=$(sandbox)
    make_stub "$box" pipx
    PATH="$box:$PATH" bash "$INSTALL" tool --url git+https://example.com/guard.git --ref v1.2.3 >/dev/null 2>&1
    assert_eq "$?" 0 "tool exit code"
    assert_file_contains "$box/calls.log" "pipx install --force git+https://example.com/guard.git@v1.2.3"
}

test_hook_installs_executable_managed_hook_and_rerun_updates() {
    # Load-bearing: behavior 5 and the hook output contract.
    local box; box=$(sandbox)
    git_repo "$box/repo"
    bash "$INSTALL" hook --repo "$box/repo" >/dev/null 2>&1
    assert_eq "$?" 0 "hook exit code"
    local hook="$box/repo/.git/hooks/pre-commit"
    [ -x "$hook" ] || fail "expected executable hook at $hook"
    assert_file_contains "$hook" "managed-by: llm-size-guard-install"
    assert_file_contains "$hook" "llm-size-guard check"
    assert_file_contains "$hook" "command -v llm-size-guard"
    # Re-run is the supported upgrade path: managed hooks are rewritten in place.
    echo "# stale extra line" >> "$hook"
    bash "$INSTALL" hook --repo "$box/repo" >/dev/null 2>&1
    assert_eq "$?" 0 "hook re-run exit code"
    assert_file_not_contains "$hook" "# stale extra line"
}

test_hook_refuses_foreign_hook_unchanged() {
    # Trust boundary: behavior 6 - operator hook content is never modified.
    local box; box=$(sandbox)
    git_repo "$box/repo"
    mkdir -p "$box/repo/.git/hooks"
    printf '#!/bin/sh\necho custom\n' > "$box/repo/.git/hooks/pre-commit"
    bash "$INSTALL" hook --repo "$box/repo" >/dev/null 2>&1
    assert_eq "$?" 1 "foreign hook exit code"
    assert_eq "$(cat "$box/repo/.git/hooks/pre-commit")" "$(printf '#!/bin/sh\necho custom')" "hook content unchanged"
}

test_make_target_creates_appends_and_is_idempotent() {
    # Load-bearing: behavior 7 - managed Makefile block.
    local box; box=$(sandbox)
    git_repo "$box/repo"
    bash "$INSTALL" make-target --repo "$box/repo" >/dev/null 2>&1
    assert_eq "$?" 0 "make-target create exit code"
    local makefile="$box/repo/Makefile"
    assert_file_contains "$makefile" "managed-by: llm-size-guard-install"
    assert_file_contains "$makefile" ".PHONY: size-guard"
    grep -q "^${TAB}llm-size-guard check$" "$makefile" || fail "expected tab-indented recipe line"
    bash "$INSTALL" make-target --repo "$box/repo" >/dev/null 2>&1
    assert_eq "$?" 0 "make-target re-run exit code"
    assert_eq "$(grep -cF 'managed-by: llm-size-guard-install' "$makefile")" 1 "single managed block after re-run"

    # Appending preserves existing Makefile content.
    local box2; box2=$(sandbox)
    git_repo "$box2/repo"
    printf 'build:\n\techo build\n' > "$box2/repo/Makefile"
    bash "$INSTALL" make-target --repo "$box2/repo" >/dev/null 2>&1
    assert_eq "$?" 0 "make-target append exit code"
    assert_file_contains "$box2/repo/Makefile" "echo build"
    assert_file_contains "$box2/repo/Makefile" ".PHONY: size-guard"
}

test_make_target_refuses_unmanaged_size_guard_target() {
    # Trust boundary: behavior 7 - unmanaged size-guard targets are refused unchanged.
    local box; box=$(sandbox)
    git_repo "$box/repo"
    printf 'size-guard:\n\techo custom\n' > "$box/repo/Makefile"
    bash "$INSTALL" make-target --repo "$box/repo" >/dev/null 2>&1
    assert_eq "$?" 1 "unmanaged target exit code"
    assert_file_not_contains "$box/repo/Makefile" "managed-by: llm-size-guard-install"
}

test_non_repo_paths_are_refused() {
    # Edge case: behavior 4 - hook and make-target require a Git work tree.
    local box; box=$(sandbox)
    mkdir "$box/plain"
    GIT_CEILING_DIRECTORIES="$box" bash "$INSTALL" hook --repo "$box/plain" >/dev/null 2>&1
    assert_eq "$?" 1 "hook non-repo exit code"
    GIT_CEILING_DIRECTORIES="$box" bash "$INSTALL" make-target --repo "$box/plain" >/dev/null 2>&1
    assert_eq "$?" 1 "make-target non-repo exit code"
    [ ! -e "$box/plain/Makefile" ] || fail "expected no Makefile written in non-repo"
}

test_usage_errors_exit_2() {
    # Edge case: behavior 1 - unknown commands and options are usage errors.
    bash "$INSTALL" >/dev/null 2>&1
    assert_eq "$?" 2 "missing command exit code"
    bash "$INSTALL" frobnicate >/dev/null 2>&1
    assert_eq "$?" 2 "unknown command exit code"
    bash "$INSTALL" tool --installer >/dev/null 2>&1
    assert_eq "$?" 2 "valueless option exit code"
    bash "$INSTALL" hook --bogus >/dev/null 2>&1
    assert_eq "$?" 2 "unknown option exit code"
    bash "$INSTALL" --help >/dev/null 2>&1
    assert_eq "$?" 0 "help exit code"
}

run_test test_tool_auto_prefers_pipx_with_default_url
run_test test_tool_forced_uv_and_pip_installers
run_test test_tool_url_and_ref_build_spec
run_test test_hook_installs_executable_managed_hook_and_rerun_updates
run_test test_hook_refuses_foreign_hook_unchanged
run_test test_make_target_creates_appends_and_is_idempotent
run_test test_make_target_refuses_unmanaged_size_guard_target
run_test test_non_repo_paths_are_refused
run_test test_usage_errors_exit_2

echo "$TESTS tests, $FAILURES failure(s)"
[ "$FAILURES" -eq 0 ]
