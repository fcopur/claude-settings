#!/usr/bin/env python3
"""Tests for statusline.py — formatting, cost arithmetic, and graceful degradation."""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import check, hook_decision, load_module, report, run_script, section, show  # noqa: E402

sl = load_module("statusline", "statusline.py")

# Strip ANSI so assertions compare text, not escape codes.
def plain(text):
    if text is None:
        return None
    out, i = [], 0
    while i < len(text):
        if text[i] == "\033":
            i = text.index("m", i) + 1
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


section("is_number — guards every field we do arithmetic on")
for value, want in [(1, True), (1.5, True), (0, True), (-1, True),
                    (True, False), (False, False), ("5", False), (None, False), ([], False)]:
    check(f"is_number({value!r})", sl.is_number(value), want)

section("fmt_tokens")
check("under 1k", sl.fmt_tokens(408), "408")
check("thousands", sl.fmt_tokens(55_600), "55.6k")
check("trailing .0 trimmed", sl.fmt_tokens(200_000), "200k")
check("millions", sl.fmt_tokens(1_000_000), "1M")
check("non-numeric", sl.fmt_tokens("lots"), "?")
check("None", sl.fmt_tokens(None), "?")

section("short_path")
home = os.path.expanduser("~")
check("home collapses", sl.short_path(home), "~")
check("under home", sl.short_path(os.path.join(home, "dev/x")), "~/dev/x")
check("outside home", sl.short_path("/opt/tool"), "/opt/tool")
check("empty", sl.short_path(""), "?")

section("pct_color thresholds")
check("10% green", sl.pct_color(10), sl.GREEN)
check("49% green", sl.pct_color(49), sl.GREEN)
check("50% yellow", sl.pct_color(50), sl.YELLOW)
check("80% red", sl.pct_color(80), sl.RED)

section("fmt_countdown — rounds to nearest minute, floors at 1m")
now = time.time()
check("2h14m", sl.fmt_countdown(now + 2 * 3600 + 14 * 60 + 5), "2h14m")
check("zero-padded minutes", sl.fmt_countdown(now + 3600 + 5 * 60 + 5), "1h05m")
check("under an hour", sl.fmt_countdown(now + 43 * 60 + 5), "43m")
check("sub-minute floors to 1m", sl.fmt_countdown(now + 30), "1m")
check("multi-day", sl.fmt_countdown(now + 30 * 3600), "1d6h")
check("already past", sl.fmt_countdown(now - 60), None)
check("exactly now", sl.fmt_countdown(now), None)
check("missing", sl.fmt_countdown(None), None)
check("string", sl.fmt_countdown("soon"), None)
check("bool", sl.fmt_countdown(True), None)

section("limit_part")
check("pct + countdown", plain(sl.limit_part("5h", {"used_percentage": 17, "resets_at": now + 8040}, True)),
      "5h 17% ·2h14m")
check("pct only when countdown off", plain(sl.limit_part("7d", {"used_percentage": 6, "resets_at": now + 99999}, False)),
      "7d 6%")
check("float noise rounded", plain(sl.limit_part("5h", {"used_percentage": 7.000000000000001}, False)), "5h 7%")
check("stale resets_at drops countdown", plain(sl.limit_part("5h", {"used_percentage": 17, "resets_at": now - 5}, True)),
      "5h 17%")
check("missing resets_at drops countdown", plain(sl.limit_part("5h", {"used_percentage": 17}, True)), "5h 17%")
check("missing pct", sl.limit_part("5h", {"resets_at": now + 60}, True), None)
check("not a dict", sl.limit_part("5h", "nope", True), None)
check("None", sl.limit_part("5h", None, True), None)

section("fmt_money")
check("dollars", sl.fmt_money(1.3455705), "$1.35")
check("exactly one dollar", sl.fmt_money(1.0), "$1.00")
check("cents", sl.fmt_money(0.054), "5.4c")
check("sub-tenth-cent", sl.fmt_money(0.0002), "<0.1c")
check("zero", sl.fmt_money(0.0), "<0.1c")

section("turn_cost")
USAGE = {"input_tokens": 2, "output_tokens": 408,
         "cache_creation_input_tokens": 1688, "cache_read_input_tokens": 53887}
per_in, per_out = 5.00 / 1e6, 25.00 / 1e6
expected = (USAGE["input_tokens"] * per_in
            + USAGE["cache_read_input_tokens"] * per_in * sl.CACHE_READ_RATE
            + USAGE["cache_creation_input_tokens"] * per_in * sl.CACHE_WRITE_RATE
            + USAGE["output_tokens"] * per_out)
check("opus 5 matches hand-computed value", round(sl.turn_cost("claude-opus-5", USAGE), 10), round(expected, 10))
show("renders as", sl.fmt_money(sl.turn_cost("claude-opus-5", USAGE)))
check("cache writes use the 1h TTL rate", sl.CACHE_WRITE_RATE, 2.0)
check("cache reads bill at 0.1x", sl.CACHE_READ_RATE, 0.1)
check("unknown model", sl.turn_cost("claude-mystery-9", USAGE), None)
check("model id absent", sl.turn_cost(None, USAGE), None)
check("usage not a dict", sl.turn_cost("claude-opus-5", "nope"), None)
check("empty usage is zero", sl.turn_cost("claude-opus-5", {}), 0)
check("null fields tolerated", sl.turn_cost("claude-opus-5", {"input_tokens": None, "output_tokens": None}), 0)
check("haiku cheaper than opus",
      sl.turn_cost("claude-haiku-4-5", USAGE) < sl.turn_cost("claude-opus-5", USAGE), True)

section("end-to-end rendering")
FULL = {
    "cwd": os.path.join(home, "dev/claude-settings"),
    "model": {"id": "claude-opus-5", "display_name": "Opus 5"},
    "context_window": {"total_input_tokens": 55_600, "context_window_size": 1_000_000,
                       "used_percentage": 6, "current_usage": USAGE},
    "rate_limits": {"five_hour": {"used_percentage": 17, "resets_at": now + 8040},
                    "seven_day": {"used_percentage": 6}},
    "cost": {"total_cost_usd": 1.3455705},
}


def render(payload):
    code, out, err = run_script("statusline.py", json.dumps(payload))
    check(f"exit 0 ({len(err.splitlines())} stderr lines)", code, 0)
    return plain(out.rstrip("\n"))


show("full payload", render(FULL))

no_limits = {k: v for k, v in FULL.items() if k != "rate_limits"}
show("no rate_limits", render(no_limits))

no_cost = {k: v for k, v in FULL.items() if k != "cost"}
show("no cost block", render(no_cost))

unknown_model = json.loads(json.dumps(FULL))
unknown_model["model"]["id"] = "claude-mystery-9"
show("unknown model id", render(unknown_model))

null_cost = json.loads(json.dumps(FULL))
null_cost["cost"]["total_cost_usd"] = None
show("null total_cost_usd", render(null_cost))

show("empty payload", render({}))

section("malformed payloads degrade instead of crashing")
for label, ctx in [
    ("used_percentage is a string", {"used_percentage": "high", "context_window_size": 1000}),
    ("total_input_tokens is a string", {"total_input_tokens": "lots", "context_window_size": 1000}),
    ("used_percentage is a bool", {"used_percentage": True, "context_window_size": 1000}),
    ("context_window is null", None),
]:
    show(label, render({"cwd": "/tmp", "context_window": ctx}))

code, out, err = run_script("statusline.py", "this is not json")
check("non-JSON stdin exits 0", code, 0)
check("non-JSON stdin says so", out.strip(), "statusline: bad input")

sys.exit(report())
