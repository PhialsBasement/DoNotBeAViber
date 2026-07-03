# Don't Be a Viber

**Don't vibe. Speed.**

One natural-language sentence in → **at most one logical unit of code** out, powered by
your own Claude Code install. You do the thinking — decomposition, control flow, data
structures. The model only transcribes your logic into syntax.

Vibing is outsourcing the thinking. Speeding is keeping every decision and collapsing
the time between *knowing what a line does* and the line existing. Same model, opposite
relationship to the work — and the gate is the line between them: the moment a request
stops being transcription and starts being delegation, it refuses.

This is not a tool for toy scripts. It's built for real projects that demand
architecture — the exact place vibe-coding does its damage. You hold the structure;
it holds the syntax. The bigger and more consistent your codebase, the better the
transcriptions get, because it reads *your* code to match *your* style.

Ask for more than one logical step and you get told: **"Don't be a viber!"** — plus your
request split into single-step sentences you can translate one at a time.

## Why

AI coding tools erode fundamentals by doing the thinking for you. But memorizing syntax
across five languages is low-value work. This tool splits the difference: you must express
program logic step by step; the model refuses anything broader than one statement, one
condition, one loop, one signature, or one small coherent block.

Every generation is human-initiated (one keypress) and human-reviewed (ghost text you
accept or discard). Every accepted pair is logged locally so you can review what syntax
you keep reaching for.

## Requirements

- **[Claude Code](https://claude.com/claude-code)** installed and logged in (`claude` on your PATH)
- **Python 3.10+** on your PATH (runs the local backend; no packages needed)
- No accounts, no API keys handled by this extension, no telemetry — everything runs locally

## Usage

1. Write a sentence describing one step, on its own line (bare or behind a comment marker):
   `loop over the items and sum their prices into subtotal`
2. Press **Ctrl+Alt+C**.
3. The generated code appears as ghost text below your sentence, with an accept toolbar.
4. **Enter** (or Tab) accepts — the code is inserted and your sentence becomes a comment.
   **Esc** discards.

If your sentence describes more than one logical unit, you get the rejection plus the
suggested split inserted as comments, each ready to translate.

The model reads your file (read-only) to match your naming and style. It has no other
tools: it cannot edit files, run commands, or access the network.

## Settings

Open the **Don't Be a Viber** icon in the activity bar for the settings panel, or use the
regular Settings UI (search "nlv").

| Setting | Default | Meaning |
|---|---|---|
| `nlv.model` | `sonnet` | Claude model alias for the warm session |
| `nlv.effort` | `low` | Effort level (low = fastest) |
| `nlv.sentenceHandling` | `comment` | Keep the sentence as a comment on accept, or strip it |
| `nlv.maxLines` | `10` | Refuse generations longer than this (over-scope guard) |
| `nlv.session.idleMinutes` | `15` | Kill the warm session after idle time |
| `nlv.pythonPath` | `python` | Interpreter for the local backend |
| `nlv.backendPath` | *(auto)* | Custom backend location (advanced) |

## Privacy & data

- Your sentences and surrounding file content go to Anthropic through **your own**
  Claude Code session, under your existing account and settings. Nothing else leaves
  your machine.
- A local learning log (`.nlv/log.jsonl`, gitignored) records your sentence → code pairs
  for your own review. It is never transmitted.

## Auth & terms note

This extension performs zero credential handling: it shells into your Claude Code install
and inherits whatever auth you configured there (subscription login, API key, Bedrock/Vertex).
Requests are strictly human-initiated — one keypress per generation. Note that Anthropic's
supported path for products that wrap Claude Code is API-key auth; whether subscription
plans cover tool-mediated use has shifted over time, and the choice of auth rests entirely
with you. Institutional deployments should use Team/Enterprise or Console API keys.
Re-verify the current Claude Code terms if in doubt.

## First request is slow?

The first translation after startup (or after the idle timeout) warms the session and
takes a few seconds extra. Subsequent requests are faster. A translation that reads your
file for context typically lands in ~3–4 s.

## How it works

```
your sentence ──ctrl+alt+c──▶ extension ──▶ local daemon ──▶ warm headless claude session
                                                              (Read-only tools, locked
                                                               transcriber prompt)
   ghost text + accept toolbar ◀── strict JSON: ok/rejected ◀──┘
```

- One warm session per workspace — that's why requests after the first are fast.
- The session's only tool is reading your file, so generated code matches your naming
  and style. It cannot edit, run commands, or touch the network.
- The granularity gate lives entirely in the session's system prompt
  (`backend/nlv/prompt.py`) — every accept/reject decision traces back to that one file.
- Anything the model returns that isn't valid, in-schema JSON is retried once and then
  refused — malformed output can never reach your editor.

## Hacking on it

```
backend/    the daemon: session lifecycle, gate prompt, protocol, learning log
extension/  the VS Code layer: keybinding, ghost text, sidebar settings
tools/      icon generator + vsix packer
```

```sh
# poke the backend directly, no editor involved
cd backend
python harness.py                    # REPL: type sentences, see accepts/rejects + latency

# tests
python test_manager.py               # lifecycle (offline, free, fast)
python test_server.py                # daemon protocol (offline, free, fast)
python test_gate.py                  # adversarial gate suite (live, uses your claude)
python test_reread.py                # context freshness (live)

# run the extension from source
code --extensionDevelopmentPath=<repo>/extension <some-folder>

# package a .vsix
python tools/build_vsix.py           # -> dist/
```

Tuning the gate = editing the prompt in `backend/nlv/prompt.py`, then running
`test_gate.py` to prove you didn't break the boundary (release bar: ≥95% of
scope-bombs rejected, 100% of single units accepted).

## Contributing

The most valuable contribution is a **gate misjudgment**: a sentence that got accepted
but shouldn't have been (over-helping), or got rejected but describes one honest logical
unit. Add it to the fixtures in `backend/test_gate.py` and open a PR — even just an
issue with the sentence and what happened is useful.

Before a PR: run the two offline suites (free); run `test_gate.py` if you touched the
prompt. Keep the extension free of dependencies and the backend free of packages —
that's a hard constraint, not a preference.
