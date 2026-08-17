#!/usr/bin/env python3
"""PreToolUse(Bash) hook: block catastrophic commands, ask about risky ones.

Emits "deny" only for commands that are unrecoverable (wiping /, $HOME, or a
raw device). Everything merely hard to undo - force pushes, hard resets,
recursive deletes outside the working tree - gets "ask", so it surfaces as a
prompt rather than a wall. Silence means the normal permission flow applies.
"""
import json
import os
import re
import shlex
import sys

# Targets where a recursive delete is unrecoverable and never intended. Compared
# with trailing slashes stripped, so "/usr" also covers "/usr/" and "/usr///".
# Both platforms' home roots and system directories are listed unconditionally
# rather than switched on sys.platform: the extra names cost nothing on the
# platform that lacks them, and a config synced between a Mac and a Linux box
# then behaves identically on each.
CATASTROPHIC_TARGETS = {
    target.rstrip("/")
    for target in (
        "/", "/*", "*", "~", "~/", "~/*", ".", "..",
        "$HOME", "${HOME}", "$HOME/", "$HOME/*",
        "/home", "/home/*", "/usr", "/etc", "/var", "/bin", "/lib", "/opt", "/boot",
        # macOS: home lives under /Users, and these are the system roots.
        "/Users", "/Users/*", "/System", "/Library", "/Applications", "/Volumes",
    )
}

# Splits a command line into pipeline segments. Not a shell parser - close
# enough to find the individual commands worth inspecting.
SEGMENT_SPLIT = re.compile(r"\|\||&&|[;|\n]")

ENV_ASSIGN = re.compile(r"^\w+=")


def segments(command):
    for raw in SEGMENT_SPLIT.split(command):
        raw = raw.strip()
        if not raw:
            continue
        try:
            argv = shlex.split(raw)
        except ValueError:
            argv = raw.split()
        # Drop leading env assignments and privilege wrappers.
        while argv and (ENV_ASSIGN.match(argv[0]) or argv[0] in ("sudo", "env", "command", "nohup")):
            argv = argv[1:]
        if argv:
            yield argv


def split_flags(argv):
    """Return (short flag letters, long flag names, positional args)."""
    short, long_, positional = set(), set(), []
    for arg in argv[1:]:
        if arg.startswith("--"):
            long_.add(arg[2:].split("=", 1)[0])
        elif arg.startswith("-") and len(arg) > 1:
            short.update(arg[1:])
        else:
            positional.append(arg)
    return short, long_, positional


def check_rm(argv):
    short, long_, targets = split_flags(argv)
    recursive = bool({"r", "R"} & short) or "recursive" in long_
    force = "f" in short or "force" in long_
    if not (recursive and force):
        return None

    for t in targets:
        # An empty target is `rm -rf ""`, which deletes nothing and just errors.
        # Skipped explicitly because "" strips to the same key as "/".
        if not t:
            continue
        if t.rstrip("/") in CATASTROPHIC_TARGETS:
            return "deny", f"`rm -rf {t}` would wipe a system or home directory. Refusing."
        # "$VAR/" collapses to "/" when VAR is unset. A bare "$VAR" does not -
        # it leaves either no argument or an empty one, both of which just
        # error out - so the trailing separator is what makes this fatal.
        if re.fullmatch(r"\$\{?\w+\}?/\*?", t):
            return "deny", (
                f"`rm -rf {t}` builds a path from a variable with a trailing slash. "
                "If it is unset this expands to `/`. Refusing."
            )

    outside = [t for t in targets if os.path.isabs(t) or t.startswith("..")]
    if outside:
        return "ask", (
            "Recursive force-delete outside the working directory: "
            + ", ".join(outside)
        )
    return None


def check_git(argv):
    args = argv[1:]
    # Skip global options like -C <dir> to find the subcommand.
    i = 0
    while i < len(args) and args[i].startswith("-"):
        i += 2 if args[i] in ("-C", "-c") else 1
    sub = args[i] if i < len(args) else None
    rest = args[i + 1:] if sub else []

    if sub == "push":
        if "--force-with-lease" in rest or any(a.startswith("--force-with-lease=") for a in rest):
            return None
        short, long_, _ = split_flags(["git"] + rest)
        if "force" in long_ or "f" in short:
            return "ask", "Force push rewrites remote history. Consider --force-with-lease."
    elif sub == "reset":
        if "--hard" in rest:
            return "ask", "`git reset --hard` discards uncommitted work irrecoverably."
    elif sub == "clean":
        short, long_, _ = split_flags(["git"] + rest)
        if ("f" in short or "force" in long_) and ({"d", "x", "X"} & short):
            return "ask", "`git clean -fd/-fx` deletes untracked and ignored files."
    elif sub == "checkout" and "--force" in rest:
        return "ask", "`git checkout --force` discards local modifications."
    return None


def check_dd(argv):
    for arg in argv[1:]:
        if arg.startswith("of=") and arg[3:].startswith("/dev/"):
            return "deny", f"`dd {arg}` writes directly to a block device. Refusing."
    return None


def check_chmod(argv):
    short, long_, positional = split_flags(argv)
    if not ("R" in short or "recursive" in long_):
        return None
    if os.path.basename(argv[0]) == "chmod" and "777" in positional:
        return "ask", "Recursive chmod 777 makes every file world-writable."
    # positional[0] is the mode/owner; the rest are paths.
    paths = positional[1:]
    if any(os.path.isabs(p) and p.rstrip("/").count("/") <= 2 for p in paths):
        return "ask", "Recursive permission change high in the filesystem."
    return None


CHECKS = {
    "rm": check_rm,
    "git": check_git,
    "dd": check_dd,
    "chmod": check_chmod,
    "chown": check_chmod,
}


def check_pipeline(command):
    """Whole-command patterns that segment-level checks cannot see."""
    if re.search(r"\bmkfs(\.\w+)?\b", command):
        return "deny", "`mkfs` formats a filesystem. Refusing."
    if re.search(r">\s*/dev/(sd|nvme|hd|vd)\w*", command):
        return "deny", "Redirecting output onto a raw block device. Refusing."
    if re.search(r"\b(curl|wget)\b[^|]*\|\s*(sudo\s+)?(ba|z|k)?sh\b", command):
        return "ask", "Piping a downloaded script straight into a shell."
    return None


def decide(command):
    verdict = check_pipeline(command)
    if verdict:
        return verdict
    asks = []
    for argv in segments(command):
        name = os.path.basename(argv[0])
        check = CHECKS.get(name)
        if not check:
            continue
        result = check(argv)
        if not result:
            continue
        if result[0] == "deny":
            return result
        asks.append(result)
    return asks[0] if asks else None


def main():
    raw = sys.stdin.read()
    try:
        event = json.loads(raw) or {}
    except ValueError:
        return

    if event.get("tool_name") != "Bash":
        return
    command = (event.get("tool_input") or {}).get("command") or ""
    if not command:
        return

    verdict = decide(command)
    if not verdict:
        return

    decision, reason = verdict
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }))


if __name__ == "__main__":
    main()
