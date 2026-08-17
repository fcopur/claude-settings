#!/usr/bin/env python3
"""Tests for hooks/writing-check.py — when the instruction is injected."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import check, hook_decision, load_module, report, run_script, section  # noqa: E402

wc = load_module("writing_check", "hooks/writing-check.py")
HOOK = "hooks/writing-check.py"

section("injects — ordinary prose")
for prompt in [
    "I want to create a portable claude settings, can you help me",
    "this dont work correct, fix it please for me now",
    "please read the settings file and tell me what is wrong with the hook",
    # A slash inside a word must not make the line read as a path (regression).
    "Read/write access is needed here",
    "and/or we could revisit this later",
    "use the input/output split here",
]:
    check(f"check   {prompt[:46]!r}", wc.should_check(prompt), True)

section("skips — nothing a writing review can do")
for label, prompt in [
    ("slash command", "/code-review high"),
    ("bash passthrough", "!ls -la"),
    ("memory prefix", "# remember this"),
    ("one word", "yes"),
    ("under MIN_WORDS", "ok go ahead"),
    ("fenced code", "```\ndef f():\n    return 1\n```"),
    ("path list", "~/dev/claude-settings/statusline.py\n/opt/build/baz.sh"),
    ("single path", "./hooks/bash-guard.py"),
    ("relative path list", "src/main.py\nsrc/util.py\nsrc/cli.py"),
    ("code lines", "const x = foo();\nlet y = bar();\nreturn x => y;"),
    ("empty", ""),
    ("whitespace only", "   \n  \n"),
]:
    check(f"skip    {label}", wc.should_check(prompt), False)

section("end-to-end")
check("prose injects the instruction",
      hook_decision(HOOK, {"prompt": "this dont work correct, fix it please"}), "inject")
check("slash command stays silent",
      hook_decision(HOOK, {"prompt": "/code-review"}), "pass")
check("missing prompt key stays silent", hook_decision(HOOK, {}), "pass")

code, out, err = run_script(HOOK, "not json")
check("non-JSON stdin exits 0", code, 0)
check("non-JSON stdin prints nothing", out.strip(), "")

code, out, err = run_script(HOOK, "")
check("empty stdin exits 0", code, 0)

sys.exit(report())
