#!/usr/bin/env python3
"""Tests for merge-settings.py — the install-time settings merge.

The load-bearing behaviour is dropped_hooks: hooks.<Event> is a list and the
merge replaces lists wholesale, so this is what stands between a re-install and
silently destroying a machine's own hooks.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import ROOT, check, report, run_script, section  # noqa: E402
from harness import load_module  # noqa: E402

ms = load_module("merge_settings", "merge-settings.py")
TRACKED = json.load(open(os.path.join(ROOT, "settings.json")))


def hook_entry(event, command, matcher=None):
    group = {"hooks": [{"type": "command", "command": command}]}
    if matcher:
        group["matcher"] = matcher
    return {"hooks": {event: [group]}}


section("dropped_hooks — what a merge would silently destroy")
check("empty existing loses nothing", ms.dropped_hooks({}, TRACKED), [])
check("tracked over itself loses nothing (re-install is quiet)",
      ms.dropped_hooks(json.loads(json.dumps(TRACKED)), TRACKED), [])
check("an event this repo does not define survives",
      ms.dropped_hooks(hook_entry("Stop", "notify-send done"), TRACKED), [])
check("same event, different command is dropped",
      ms.dropped_hooks(hook_entry("UserPromptSubmit", "bash ~/mine.sh"), TRACKED),
      [("UserPromptSubmit", "*", "bash ~/mine.sh")])
check("same event, different matcher is dropped",
      ms.dropped_hooks(hook_entry("PreToolUse", "bash ~/w.sh", "Write"), TRACKED),
      [("PreToolUse", "Write", "bash ~/w.sh")])
check("an identical entry is not reported",
      ms.dropped_hooks(hook_entry("PreToolUse", "python3 ~/.claude/hooks/bash-guard.py", "Bash"), TRACKED), [])

section("dropped_hooks — malformed input does not crash")
check("hooks is not a dict", ms.dropped_hooks({"hooks": "nope"}, TRACKED), [])
check("event value is not a list", ms.dropped_hooks({"hooks": {"PreToolUse": "x"}}, TRACKED), [])
check("group missing hooks key", ms.dropped_hooks({"hooks": {"PreToolUse": [{"matcher": "Bash"}]}}, TRACKED), [])
check("group is not a dict", ms.dropped_hooks({"hooks": {"PreToolUse": ["x"]}}, TRACKED), [])

section("deep_merge")
check("nested dicts merge", ms.deep_merge({"a": {"x": 1, "y": 2}}, {"a": {"y": 9}}), {"a": {"x": 1, "y": 9}})
check("lists are replaced wholesale", ms.deep_merge({"a": [1, 2, 3]}, {"a": [4]}), {"a": [4]})
check("undefined keys are preserved", ms.deep_merge({"keep": 1}, {"new": 2}), {"keep": 1, "new": 2})
check("scalar replaces dict", ms.deep_merge({"a": {"x": 1}}, {"a": 5}), {"a": 5})

section("do_check / do_apply")
with tempfile.TemporaryDirectory() as tmp:
    source = os.path.join(tmp, "source.json")
    json.dump(TRACKED, open(source, "w"))
    missing = os.path.join(tmp, "absent.json")
    backups = os.path.join(tmp, "backups")

    check("--check on a missing target is clean", ms.do_check(missing, source), 0)

    conflicting = os.path.join(tmp, "conflicting.json")
    json.dump(hook_entry("UserPromptSubmit", "bash ~/mine.sh"), open(conflicting, "w"))
    check("--check with a conflict signals EXIT_WOULD_DROP",
          ms.do_check(conflicting, source), ms.EXIT_WOULD_DROP)

    check("--apply creates a missing target", ms.do_apply(missing, source, backups), 0)
    check("target now exists", os.path.exists(missing), True)
    check("no backup taken for a new file", os.path.isdir(backups), False)

    check("--apply over an existing file", ms.do_apply(conflicting, source, backups), 0)
    check("existing file was backed up", len(os.listdir(backups)), 1)
    check("hook list was replaced",
          json.load(open(conflicting))["hooks"]["UserPromptSubmit"], TRACKED["hooks"]["UserPromptSubmit"])

    check("bad argv returns EXIT_ERROR", ms.main(["--bogus"]), ms.EXIT_ERROR)

section("CLI — clean errors, never a traceback")
code, out, err = run_script("merge-settings.py", "", ["--check", "/nonexistent/a.json", "/nonexistent/b.json"])
check("missing source exits 1", code, 1)
check("missing source has no traceback", "Traceback" in err, False)
check("missing source explains itself", err.strip(), "error: /nonexistent/b.json not found")

with tempfile.TemporaryDirectory() as tmp:
    broken = os.path.join(tmp, "broken.json")
    open(broken, "w").write("{ not json")
    source = os.path.join(tmp, "source.json")
    json.dump(TRACKED, open(source, "w"))
    code, out, err = run_script("merge-settings.py", "", ["--check", broken, source])
    check("invalid JSON target exits 1", code, 1)
    check("invalid JSON target has no traceback", "Traceback" in err, False)
    check("invalid JSON target refuses to continue", "refusing to continue" in err, True)

sys.exit(report())
