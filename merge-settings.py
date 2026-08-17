#!/usr/bin/env python3
"""Merge this repo's settings.json into an existing ~/.claude/settings.json.

Install-time helper for install.sh; not copied into ~/.claude. Two modes:

  --check TARGET SOURCE
      Report hook entries in TARGET that the merge would discard.
      Exit 0 = nothing lost, 10 = entries listed on stdout, 1 = error.

  --apply TARGET SOURCE BACKUP_DIR
      Back TARGET up, merge, write. Exit 0 = done, 1 = error.

Keeping the prompt in install.sh (which owns the terminal) rather than here
means every branch of this file is reachable from a plain unit test.
"""
import json
import os
import shutil
import sys
from datetime import datetime

EXIT_ERROR = 1
EXIT_WOULD_DROP = 10


def deep_merge(base, incoming):
    """Recursively merge incoming into base. Incoming wins on conflict;
    lists and scalars are replaced wholesale rather than concatenated."""
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def hook_commands(entries):
    """Flatten one event's hook list into (matcher, command) pairs."""
    pairs = []
    if not isinstance(entries, list):
        return pairs
    for group in entries:
        if not isinstance(group, dict):
            continue
        matcher = group.get("matcher", "*")
        hooks = group.get("hooks")
        if not isinstance(hooks, list):
            continue
        for hook in hooks:
            if isinstance(hook, dict) and hook.get("command"):
                pairs.append((matcher, hook["command"]))
    return pairs


def dropped_hooks(existing, tracked):
    """Hook entries in existing that merging tracked over it would discard.

    Only events tracked defines are at risk: hooks.<Event> is a list, and the
    merge replaces lists wholesale. An event tracked says nothing about is
    left alone entirely.
    """
    losses = []
    existing_hooks = existing.get("hooks")
    tracked_hooks = tracked.get("hooks")
    if not isinstance(existing_hooks, dict) or not isinstance(tracked_hooks, dict):
        return losses
    for event, tracked_entries in tracked_hooks.items():
        keeping = set(hook_commands(tracked_entries))
        for pair in hook_commands(existing_hooks.get(event)):
            if pair not in keeping:
                losses.append((event,) + pair)
    return losses


MISSING = object()


def load(path, default=MISSING):
    """Read a JSON file. Without a default, a missing file is a clean error
    rather than a traceback; invalid JSON always is."""
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        if default is MISSING:
            sys.exit(f"error: {path} not found")
        return default
    except ValueError as exc:
        sys.exit(f"error: {path} is not valid JSON ({exc}); refusing to continue")


def do_check(target, source):
    losses = dropped_hooks(load(target, {}), load(source))
    if not losses:
        return 0
    for event, matcher, command in losses:
        print(f"  {event}  [{matcher}]  {command}")
    return EXIT_WOULD_DROP


def do_apply(target, source, backup_dir):
    settings = load(target, {})
    tracked = load(source)

    if os.path.exists(target):
        os.makedirs(backup_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = os.path.join(backup_dir, f"settings.json.{stamp}")
        shutil.copy2(target, backup)
        print(f"backed up: {backup}")

    with open(target, "w") as f:
        json.dump(deep_merge(settings, tracked), f, indent=2)
        f.write("\n")
    print(f"updated:   {target}")
    return 0


def main(argv):
    if len(argv) >= 3 and argv[0] == "--check":
        return do_check(argv[1], argv[2])
    if len(argv) >= 4 and argv[0] == "--apply":
        return do_apply(argv[1], argv[2], argv[3])
    print(__doc__.strip(), file=sys.stderr)
    return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
