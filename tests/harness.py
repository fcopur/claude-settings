#!/usr/bin/env python3
"""Minimal assertion harness shared by the test files in this directory.

Deliberately not pytest: the repo's whole premise is stdlib-only portability,
and a test suite that needs `pip install` to run undermines that.
"""
import importlib.util
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_failures = []


def load_module(name, relative_path):
    """Import a repo script by path (they are scripts, not an installed package)."""
    path = os.path.join(ROOT, relative_path)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def section(title):
    print(f"\n=== {title} ===")


def check(name, got, want):
    ok = got == want
    if not ok:
        _failures.append(name)
    print(f"  [{'ok ' if ok else 'FAIL'}] {name}")
    if not ok:
        print(f"         got  {got!r}")
        print(f"         want {want!r}")
    return ok


def show(name, value):
    """Record an observation with no pass/fail - for rendered output samples."""
    print(f"  [--- ] {name}: {value}")


def run_script(relative_path, stdin_text, args=()):
    """Run a repo script as a subprocess. Returns (returncode, stdout, stderr)."""
    proc = subprocess.run(
        [sys.executable, os.path.join(ROOT, relative_path), *args],
        input=stdin_text, capture_output=True, text=True,
    )
    return proc.returncode, proc.stdout, proc.stderr


def hook_decision(relative_path, event):
    """Run a hook and return its decision, or "pass" when it stays silent."""
    code, out, err = run_script(relative_path, json.dumps(event))
    assert code == 0, f"{relative_path} exited {code}: {err}"
    if not out.strip():
        return "pass"
    payload = json.loads(out)["hookSpecificOutput"]
    return payload.get("permissionDecision", "inject")


def report():
    print()
    if _failures:
        print(f"{len(_failures)} FAILURE(S): {', '.join(_failures)}")
        return 1
    print("ALL PASS")
    return 0
