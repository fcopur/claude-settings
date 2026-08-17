# claude-settings

Portable [Claude Code](https://claude.com/claude-code) configuration — status
line, hooks, and base settings — installable on any machine with `python3`.

```sh
./install.sh          # prompts if it would drop an existing hook
./install.sh --yes    # no prompt, for non-interactive use
```

## What gets installed

| Repo file | Destination |
| --- | --- |
| `statusline.py` | `~/.claude/statusline.py` |
| `hooks/writing-check.py` | `~/.claude/hooks/writing-check.py` |
| `hooks/bash-guard.py` | `~/.claude/hooks/bash-guard.py` |
| `settings.json` | deep-merged into `~/.claude/settings.json` |
| `merge-settings.py` | not installed — install-time helper only |
| `tests/` | not installed — see [Tests](#tests) |

Everything is stdlib Python — no `jq`, no bashisms (the installer runs under
`dash` and `bash` alike), and paths in `settings.json` use `~` rather than an
absolute home directory.

Runs on macOS and Linux. The only requirement is `python3` on `PATH`; macOS
doesn't ship it by default, so you may need Xcode Command Line Tools
(`xcode-select --install`) or Homebrew first. Nothing here shells out to GNU
coreutils, so BSD `sed`/`grep` on macOS are fine.

## What the merge does and does not overwrite

The merge is recursive and **tracked keys win**, so re-running the installer
pushes updates through while leaving machine-local keys alone. Concretely, given
a machine that already has its own config:

| Existing key | Result |
| --- | --- |
| `model`, `theme`, `permissions.defaultMode` | overwritten — this repo defines them |
| `outputStyle`, `env.*` | preserved — this repo doesn't define them |
| `permissions.allow` / `deny` | preserved — this repo doesn't define them |
| `hooks.Stop` | preserved — this repo defines no `Stop` hook |
| `hooks.UserPromptSubmit`, `hooks.PreToolUse` | **replaced** — see below |

`hooks.<Event>` is a *list*, and the merge replaces lists wholesale rather than
appending. So on an event this repo defines, the machine's own entries for that
event are discarded — including ones with a different `matcher`. That keeps the
repo authoritative (removing a hook here actually removes it) at the cost of
being destructive on a machine that already had hooks.

To make that non-silent, the installer lists exactly what would be dropped and
asks before writing anything:

```text
warning: these hook entries in ~/.claude/settings.json will be replaced.
Hook lists are replaced wholesale, not appended to:

  UserPromptSubmit  [*]      bash ~/my-own-prompt-hook.sh
  PreToolUse        [Write]  bash ~/my-write-guard.sh

A backup is written to ~/.claude/backups first, so this is recoverable.
Continue? [y/N]
```

Declining leaves the machine completely untouched — the check runs before any
file is copied. With nothing to drop the installer is silent, so ordinary
re-runs never prompt. `--yes` skips the prompt; without a terminal to ask on,
the install aborts rather than assuming yes.

`~/.claude/settings.json` is copied to `~/.claude/backups/settings.json.<timestamp>`
before every write, and a target that isn't valid JSON is refused rather than
overwritten.

Never touched at all: `settings.local.json`, project-level `.claude/settings.json`,
`CLAUDE.md`, `~/.claude.json` (MCP servers), and the `agents/`, `commands/`, and
`plugins/` directories.

## Status line

```text
~/dev/claude-settings (main)  Opus 5  ctx 100.3k/1M 10%  5h 17% ·2h14m  7d 6%  $1.35 ·5.4c/turn
```

Working directory (with `~` collapsed), git branch, model, context usage, both
rate-limit windows, and cost. All percentages are colour-coded green / yellow
(≥50%) / red (≥80%).

`5h 17% ·2h14m` means 17% of the rolling 5-hour quota is used and the window
clears in 2h14m. The 7-day window shows a percentage only — its reset is days
out, so the countdown is long and rarely actionable. Both windows are declared
in the `RATE_LIMITS` tuple at the top of `statusline.py`; flip the third field
to `True` to give the 7-day window a countdown too, or drop a row to hide it.

A window missing from the payload is simply omitted, and a `resets_at` already
in the past drops the countdown rather than showing a negative one. Countdowns
round to the nearest minute with a 1-minute floor, so they never read `0m`
while time remains.

Context usage is `total_input_tokens` — *not* input plus output, which would
double-count, since output tokens are folded into the next request's input.

### Cost

Two different numbers, because "what does this cost" has two readings:

- **`$1.35`** — the session total, read straight from `cost.total_cost_usd` in
  the payload. Claude Code computes it; no rate table involved, so it never
  drifts.
- **`4.8c/turn`** — the marginal cost of one more turn at the current context,
  computed from `context_window.current_usage` and the rates in `MODEL_RATES`
  at the top of `statusline.py`. This *is* a hardcoded table and will drift when
  pricing changes; a model with no entry simply hides the per-turn figure rather
  than guessing.

The per-turn number lands well below `context × headline rate` because a warm
session is mostly cache reads, which bill at ~0.1× the input rate. Cache writes
bill at 2× on the 1-hour TTL that Claude Code sessions use (the 5-minute TTL
would be 1.25× — `CACHE_WRITE_RATE` picks which).

The session total is Claude Code's own figure and is the accurate one; the
per-turn number is this script's estimate from the same list rates.

**On a Max or Pro subscription these are notional** — you're rate-limited, not
billed per token, so read them as "what this would have cost on the API." The
`5h` / `7d` windows are the figures that actually constrain you.

The branch is read straight from `.git/HEAD` rather than by shelling out to
`git`, since the status line re-renders frequently. Worktrees and submodules
(where `.git` is a file) are handled.

## Hooks

### `writing-check.py` — `UserPromptSubmit`

Asks Claude to open its response with a compact `Writing notes:` section when
the prompt contains clear-cut typos or grammar errors.

The instruction is ~700 characters, so the hook stays quiet when a review can't
help and only pays that cost when it can. It skips prompts that:

- start with `/`, `!`, or `#` (slash command, bash passthrough, memory)
- contain a fenced code block
- have fewer than four words
- are more than half code-like lines (keywords, paths, trailing `;{}(),:`,
  operators such as `::`, `=>`, `->`)

### `bash-guard.py` — `PreToolUse`, matcher `Bash`

Inspects the command before it runs and returns `deny` or `ask`. Staying silent
lets the normal permission flow apply, which matters because
`permissions.defaultMode` is `auto`.

> **This is not a security boundary.** It is a guard against fat-finger
> accidents, and it is trivially bypassed by anything actively trying to get
> around it — a variable, an alias, a `bash -c` string, a script. Read the two
> lists below as "the shapes it recognises", not "the things it can stop."

**Denied** (unrecoverable):

- `rm -rf` targeting `/`, `~`, `$HOME`, `/usr`, `/etc`, … or a variable with a
  trailing slash — `rm -rf $VAR/` becomes `rm -rf /` when `VAR` is unset. A bare
  `rm -rf $VAR` passes: unset, it leaves no argument or an empty one, and both
  just error out harmlessly.
- `dd of=/dev/…`, `mkfs`, redirecting into `/dev/sd*`

**Asked** (hard to undo, sometimes legitimate):

- `rm -rf` on an absolute path or one starting `..`
- `git push --force` (plain `--force-with-lease` passes through)
- `git reset --hard`, `git clean -fd`/`-fx`, `git checkout --force`
- recursive `chmod 777`, or recursive `chmod`/`chown` high in the filesystem
- piping `curl`/`wget` output straight into a shell

Commands are split on `;`, `|`, `&&`, `||` and newlines, then tokenised with
`shlex`; leading env assignments and `sudo`/`env`/`nohup` wrappers are stripped
before the command name is matched. That is pattern-matching, not shell parsing,
which is why the caveat above holds. It errs toward `ask`, which is recoverable,
over `deny`.

The protected-path list covers both Linux and macOS roots unconditionally —
`/home` and `/Users`, plus `/System`, `/Library`, `/Applications`, `/Volumes`.
Listing both costs nothing on the platform that lacks them and keeps a config
synced across machines behaving identically on each.

## Tests

```sh
./tests/run.sh        # summary
./tests/run.sh -v     # every assertion
```

Stdlib only — no pytest, no `pip install`, matching the constraint the code
itself is built under. Each suite is a plain script you can also run directly:

| Suite | Covers |
| --- | --- |
| `test_statusline.py` | formatting, cost arithmetic, malformed-payload degradation |
| `test_bash_guard.py` | the deny / ask / pass matrix |
| `test_writing_check.py` | when the instruction is injected vs skipped |
| `test_merge_settings.py` | dropped-hook detection, merge semantics, exit codes |

`run.sh` also syntax-checks the shell scripts, and returns non-zero if anything
fails, so it works as a pre-commit or CI step.

**The pass cases carry as much weight as the failure cases.** `bash-guard`'s
value depends on `rm -rf node_modules` and `chmod +x install.sh` going through
untouched — a guard that interrupts routine work gets disabled, and then it
protects nothing. Likewise the writing hook is tested on prose containing
slashes (`Read/write access`), which a previous version misread as a file path
and silently skipped.

One gap worth stating: the interactive `read` in `install.sh` is not covered.
Exercising it needs a controlling terminal, which the environment this was
developed in did not provide. The answer-matching logic around it was verified
separately; the prompt-and-read plumbing was not.

## License

[MIT](LICENSE).
