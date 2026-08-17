#!/usr/bin/env python3
"""UserPromptSubmit hook: ask for a short writing review of the user's prompt.

Injection is skipped when a review would just be noise - slash commands, bash
and memory prefixes, very short prompts, and prompts that are mostly code,
paths, or pasted output. Skipping keeps the ~700 characters of instructions out
of turns that can't benefit from them.
"""
import json
import re
import sys

INSTRUCTION = (
    "WRITING CHECK: Before responding, scan the user message for: typos, "
    "spelling mistakes, grammar errors, wrong word order, missing articles "
    "(a/an/the), wrong prepositions, poor word choice, ambiguous references "
    "(unclear what 'this' or 'it' refers to), and phrases where a clearly "
    "better alternative exists. Only flag clear-cut issues, not style "
    "preferences. If issues exist, show a compact 'Writing notes:' section at "
    "the very top of your response using bullets: original -> correction (one "
    "line per issue, no explanations). If the message is correct, skip the "
    "section entirely. Never let the writing check dominate the response."
)

MIN_WORDS = 4

# Prefixes Claude Code treats specially: slash command, bash passthrough, memory.
SKIP_PREFIXES = ("/", "!", "#")

CODE_KEYWORD = re.compile(
    r"^\s*(def|class|function|import|from|const|let|var|return|export|"
    r"public|private|package|fn|impl|struct)\b"
)
CODE_TAIL = re.compile(r"[;{}(),:]\s*$")
CODE_INFIX = re.compile(r"(::|=>|->|\|\||&&|\$\(|==|!=)")
# A whole line that is nothing but a path. Anchored at both ends on purpose:
# matching a bare slash mid-line classified ordinary prose ("Read/write access
# is needed") as code, which silently skipped the check on one-line prompts.
PATH_LINE = re.compile(r"^\s*(?:[~.]?/|\w+/)[\w./-]+$")
WORD = re.compile(r"[A-Za-z][A-Za-z'-]*")


def looks_like_code(line):
    return bool(
        CODE_KEYWORD.search(line)
        or CODE_TAIL.search(line)
        or CODE_INFIX.search(line)
        or PATH_LINE.match(line)
    )


def should_check(prompt):
    stripped = prompt.strip()
    if not stripped or stripped.startswith(SKIP_PREFIXES):
        return False
    if "```" in stripped:
        return False
    if len(WORD.findall(stripped)) < MIN_WORDS:
        return False

    lines = [ln for ln in stripped.splitlines() if ln.strip()]
    if lines and sum(looks_like_code(ln) for ln in lines) * 2 > len(lines):
        return False
    return True


def main():
    # Always drain stdin: the hook is handed the event JSON there, and leaving
    # it unread can hand the writer a broken pipe.
    raw = sys.stdin.read()
    try:
        prompt = (json.loads(raw) or {}).get("prompt", "")
    except ValueError:
        prompt = ""

    if not should_check(prompt):
        return

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": INSTRUCTION,
        }
    }))


if __name__ == "__main__":
    main()
