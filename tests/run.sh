#!/bin/sh
# Runs every test suite. Exits non-zero if any of them fail.
# No dependencies beyond python3 - same constraint as the code under test.
set -eu

TESTS_DIR=$(cd "$(dirname "$0")" && pwd)
ROOT=$(dirname "$TESTS_DIR")

if ! command -v python3 >/dev/null 2>&1; then
    echo "error: python3 not found on PATH" >&2
    exit 1
fi

verbose=0
[ "${1:-}" = "-v" ] && verbose=1

failed=0
for suite in "$TESTS_DIR"/test_*.py; do
    name=$(basename "$suite" .py)
    if [ "$verbose" -eq 1 ]; then
        printf '\n########## %s ##########\n' "$name"
        python3 "$suite" || failed=$((failed + 1))
        continue
    fi
    output=$(python3 "$suite" 2>&1) || failed=$((failed + 1))
    passed=$(printf '%s\n' "$output" | grep -c '\[ok \]' || true)
    if printf '%s\n' "$output" | grep -q 'FAIL'; then
        printf '  FAIL  %-22s %s passing\n' "$name" "$passed"
        printf '%s\n' "$output" | grep -A2 'FAIL' | sed 's/^/        /'
    else
        printf '  ok    %-22s %s assertions\n' "$name" "$passed"
    fi
done

# Shell scripts are part of the deliverable too.
for script in "$ROOT"/install.sh "$TESTS_DIR"/run.sh; do
    if sh -n "$script" 2>/dev/null; then
        printf '  ok    %-22s syntax\n' "$(basename "$script")"
    else
        printf '  FAIL  %-22s syntax\n' "$(basename "$script")"
        failed=$((failed + 1))
    fi
done

echo
if [ "$failed" -eq 0 ]; then
    echo "all suites passed"
else
    echo "$failed suite(s) failed"
    exit 1
fi
