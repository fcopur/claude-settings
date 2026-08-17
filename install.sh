#!/bin/sh
# Installs the portable Claude Code config into ~/.claude:
#   - statusline.py
#   - hooks/*.py
#   - settings.json, deep-merged into any existing one (tracked keys win)
#
# Machine-local settings this repo does not define are preserved. Hook lists
# ARE replaced wholesale, so any existing hook entries that would be dropped
# are listed and confirmed before anything is written.
#
# Usage: ./install.sh [-y|--yes]    -y skips the prompt (non-interactive use)
set -eu

ASSUME_YES=0
for arg in "$@"; do
    case "$arg" in
        -y|--yes) ASSUME_YES=1 ;;
        -h|--help) echo "usage: $0 [-y|--yes]"; exit 0 ;;
        *) echo "error: unknown argument: $arg" >&2; exit 2 ;;
    esac
done

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
CLAUDE_DIR="$HOME/.claude"
SETTINGS="$CLAUDE_DIR/settings.json"
BACKUP_DIR="$CLAUDE_DIR/backups"

for required in statusline.py settings.json merge-settings.py hooks; do
    if [ ! -e "$SCRIPT_DIR/$required" ]; then
        echo "error: $required must be next to install.sh" >&2
        exit 1
    fi
done

if ! command -v python3 >/dev/null 2>&1; then
    echo "error: python3 not found on PATH" >&2
    exit 1
fi

MERGE="python3 $SCRIPT_DIR/merge-settings.py"

# Check before writing anything, so declining leaves the machine untouched.
set +e
DROPPED=$($MERGE --check "$SETTINGS" "$SCRIPT_DIR/settings.json")
CHECK_STATUS=$?
set -e

if [ "$CHECK_STATUS" -eq 10 ]; then
    echo
    echo "warning: these hook entries in $SETTINGS will be replaced."
    echo "Hook lists are replaced wholesale, not appended to:"
    echo
    echo "$DROPPED"
    echo
    echo "A backup is written to $BACKUP_DIR first, so this is recoverable."
    if [ "$ASSUME_YES" -eq 0 ]; then
        if [ -t 0 ]; then
            printf 'Continue? [y/N] '
            read -r answer
        elif (exec 3< /dev/tty) 2>/dev/null; then
            # Piped install (curl | sh): stdin is the script, so ask the terminal.
            # Probed in a subshell by actually opening it - /dev/tty can exist
            # and be readable by mode yet still fail with ENXIO when there is no
            # controlling terminal, and a failed redirection on a special
            # built-in such as ":" would take the whole shell down with it.
            printf 'Continue? [y/N] ' > /dev/tty
            read -r answer < /dev/tty
        else
            echo "aborted: no terminal to confirm on; re-run with --yes to proceed" >&2
            exit 1
        fi
        case "$answer" in
            y|Y|yes|YES) ;;
            *) echo "aborted: nothing was modified"; exit 1 ;;
        esac
    fi
    echo
elif [ "$CHECK_STATUS" -ne 0 ]; then
    exit "$CHECK_STATUS"
fi

mkdir -p "$CLAUDE_DIR/hooks" "$BACKUP_DIR"

$MERGE --apply "$SETTINGS" "$SCRIPT_DIR/settings.json" "$BACKUP_DIR"

cp "$SCRIPT_DIR/statusline.py" "$CLAUDE_DIR/statusline.py"
chmod +x "$CLAUDE_DIR/statusline.py"
echo "installed: $CLAUDE_DIR/statusline.py"

for hook in "$SCRIPT_DIR"/hooks/*.py; do
    [ -e "$hook" ] || continue
    cp "$hook" "$CLAUDE_DIR/hooks/"
    chmod +x "$CLAUDE_DIR/hooks/$(basename "$hook")"
    echo "installed: $CLAUDE_DIR/hooks/$(basename "$hook")"
done

echo
echo "Restart Claude Code (or start a new session) to pick up the changes."
