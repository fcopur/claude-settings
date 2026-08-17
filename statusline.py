#!/usr/bin/env python3
"""Claude Code status line: cwd, git branch, model, context usage, rate limits.

Reads the status line payload as JSON on stdin and prints a single line.
Deliberately dependency-free (stdlib only) so it runs anywhere python3 does.
"""
import json
import os
import sys
import time

RESET = "\033[0m"
DIM = "\033[2m"
BOLD = "\033[1m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"

# Rate-limit windows to display: (label, payload key, show reset countdown).
# The 7-day window resets days out, so a countdown there is long and rarely
# actionable - flip its flag to True if you want it anyway.
RATE_LIMITS = (
    ("5h", "five_hour", True),
    ("7d", "seven_day", False),
)

# Per-million-token list prices in USD, for the marginal per-turn cost below.
# The session total comes from the payload and needs no table; this does, so it
# drifts when pricing changes - an unlisted model just hides the per-turn figure.
# Sonnet 5 carries introductory pricing of $2/$10 through 2026-08-31.
MODEL_RATES = {
    "claude-opus-5": (5.00, 25.00),
    "claude-fable-5": (10.00, 50.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
}
CACHE_READ_RATE = 0.1   # cache reads bill at ~0.1x the input rate
CACHE_WRITE_RATE = 2.0  # 1-hour TTL, which is what Claude Code sessions use.
                        # The 5-minute TTL bills writes at 1.25x instead.


def is_number(value):
    """True for a real number. Guards every payload field we do arithmetic on:
    a malformed value would otherwise crash the whole line, and bools are ints
    in Python but are never a count, a percentage, or a timestamp."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def fmt_tokens(n):
    if not is_number(n):
        return "?"
    for limit, suffix in ((1_000_000, "M"), (1000, "k")):
        if n >= limit:
            text = f"{n / limit:.1f}"
            return (text[:-2] if text.endswith(".0") else text) + suffix
    return str(n)


def short_path(path):
    if not path:
        return "?"
    home = os.path.expanduser("~")
    if path == home:
        return "~"
    if path.startswith(home + os.sep):
        return "~" + path[len(home):]
    return path


def git_branch(cwd):
    """Read the branch straight out of .git/HEAD - no subprocess per render."""
    d = cwd
    while True:
        git = os.path.join(d, ".git")
        head = None
        if os.path.isdir(git):
            head = os.path.join(git, "HEAD")
        elif os.path.isfile(git):
            # worktree or submodule: .git is a file pointing at the real gitdir
            try:
                with open(git) as f:
                    line = f.read().strip()
            except OSError:
                return None
            if line.startswith("gitdir:"):
                head = os.path.join(line[len("gitdir:"):].strip(), "HEAD")
        if head:
            try:
                with open(head) as f:
                    ref = f.read().strip()
            except OSError:
                return None
            prefix = "ref: refs/heads/"
            if ref.startswith(prefix):
                return ref[len(prefix):]
            return ref[:7]  # detached HEAD
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def pct_color(pct):
    if pct >= 80:
        return RED
    if pct >= 50:
        return YELLOW
    return GREEN


def fmt_countdown(resets_at):
    """Time until a unix timestamp, as "2h14m" / "43m". None if absent or past."""
    if not is_number(resets_at):
        return None
    remaining = resets_at - time.time()
    if remaining <= 0:
        return None
    # Round to the nearest minute rather than truncating - truncating turns a
    # reset exactly 2h14m out into "2h13m". Floored at 1m so a countdown with
    # time left never reads "0m", which would look like it had already reset.
    total_minutes = max(1, round(remaining / 60))
    hours, minutes = divmod(total_minutes, 60)
    if hours >= 24:
        days, hours = divmod(hours, 24)
        return f"{days}d{hours}h"
    if hours:
        return f"{hours}h{minutes:02d}m"
    return f"{minutes}m"


def fmt_money(usd):
    """Dollars above a dollar, cents below - "$1.35" / "4.8c" / "<0.1c"."""
    if usd >= 1:
        return f"${usd:.2f}"
    cents = usd * 100
    if cents < 0.1:
        return "<0.1c"
    return f"{cents:.1f}c"


def turn_cost(model_id, usage):
    """List cost of the last request: what one more turn at this context costs.

    Cache reads dominate once a session is warm, which is why this lands far
    below input_tokens x the headline rate. None if the model has no rate entry.
    """
    rates = MODEL_RATES.get(model_id)
    if not rates or not isinstance(usage, dict):
        return None
    per_input, per_output = (rate / 1_000_000 for rate in rates)
    return (
        (usage.get("input_tokens") or 0) * per_input
        + (usage.get("cache_read_input_tokens") or 0) * per_input * CACHE_READ_RATE
        + (usage.get("cache_creation_input_tokens") or 0) * per_input * CACHE_WRITE_RATE
        + (usage.get("output_tokens") or 0) * per_output
    )


def limit_part(label, limit, with_countdown):
    """Render one rate-limit window, or None if the payload lacks it."""
    if not isinstance(limit, dict):
        return None
    pct = limit.get("used_percentage")
    if not is_number(pct):
        return None
    text = f"{DIM}{label}{RESET} {pct_color(pct)}{pct:.0f}%{RESET}"
    if with_countdown:
        countdown = fmt_countdown(limit.get("resets_at"))
        if countdown:
            text += f"{DIM} ·{countdown}{RESET}"
    return text


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        print("statusline: bad input")
        return

    cwd = data.get("cwd") or (data.get("workspace") or {}).get("current_dir") or ""
    model = data.get("model") or {}
    ctx = data.get("context_window") or {}

    parts = []

    loc = short_path(cwd)
    branch = git_branch(cwd) if cwd else None
    if branch:
        loc = f"{loc} {DIM}({branch}){RESET}"
    parts.append(loc)

    parts.append(f"{BOLD}{CYAN}{model.get('display_name', '?')}{RESET}")

    # total_input_tokens is already the full size of the last request's context;
    # output tokens are folded into the next request, so adding them double-counts.
    used_tok = ctx.get("total_input_tokens")
    window = ctx.get("context_window_size")
    tok_str = f"{fmt_tokens(used_tok)}/{fmt_tokens(window)}" if window else "?"

    used_pct = ctx.get("used_percentage")
    if is_number(used_pct):
        pct_str, color = f"{used_pct:.0f}%", pct_color(used_pct)
    else:
        pct_str, color = "?%", DIM
    parts.append(f"{DIM}ctx{RESET} {tok_str} {color}{pct_str}{RESET}")

    limits = data.get("rate_limits") or {}
    for label, key, with_countdown in RATE_LIMITS:
        part = limit_part(label, limits.get(key), with_countdown)
        if part:
            parts.append(part)

    session_usd = (data.get("cost") or {}).get("total_cost_usd")
    if is_number(session_usd):
        cost = fmt_money(session_usd)
        per_turn = turn_cost(model.get("id"), ctx.get("current_usage"))
        # A zero per-turn cost means the payload carried no usage yet - there is
        # nothing useful to show, so fall back to the session total alone.
        if per_turn:
            cost += f"{DIM} ·{fmt_money(per_turn)}/turn{RESET}"
        parts.append(cost)

    print("  ".join(parts))


if __name__ == "__main__":
    main()
