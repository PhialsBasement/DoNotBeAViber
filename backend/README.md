# nlv backend (complete — no VS Code yet)

Warm `claude` CLI session over stream-JSON stdio. Python 3.14, stdlib only.

```
python server.py --workspace <root>        # THE daemon VS Code will spawn (NDJSON stdio)
python harness.py                          # REPL (:lang <id>, :file <path> [line], :q)
python harness.py --once "sentence"        # one-shot
python test_gate.py                        # adversarial gate suite (live, ~20 requests)
python test_reread.py                      # context-staleness test (live)
python test_manager.py                     # lifecycle tests (offline, fake claude)
python test_server.py                      # daemon e2e tests (offline, fake claude)
```

## Layout

- `nlv/session.py` — spawns `claude -p --input-format stream-json --output-format stream-json`,
  keeps the process alive, one blocking `send()` per request; `kill()` for cancel
- `nlv/manager.py` — lifecycle + policy: lazy spawn, idle reap, crash -> one
  respawn, cancel, one silent retry on malformed output, over-scope guard
- `nlv/protocol.py` — request payload build + strict response validation
- `nlv/prompt.py` — the transcriber system prompt (the ONLY gate) + response JSON schema
- `nlv/log.py` — `.nlv/log.jsonl` learning log (gitignored dir, append-only)
- `server.py` — the stdio daemon (translate / cancel / restart / status /
  logEvent / shutdown); UTF-8 stdio forced; drains in-flight work on EOF
- `fake_claude.py` — deterministic CLI stand-in for the offline tests

## Validated 2026-07-03 (claude CLI 2.1.199, subscription auth)

- Warm session works: N sequential single-turn requests through one process.
- `--json-schema` → CLI forces a `StructuredOutput` tool call; `result` event
  carries parsed `structured_output`. No text parsing needed.
- `--tools "Read"` + `--system-prompt` (replaces default) + `--no-session-persistence`
  + `--strict-mcp-config` + `--disable-slash-commands` = clean locked-down session.
- Context via Read tool (2026-07-03): payload sends `file` + `line` instead of
  contextBefore; the model reads a window around the cursor itself. Verified:
  camelCase fixture produced `self.failedCount += 1` / `self.pendingOrders` —
  exact names from the file. Cost: ~2 s extra per request that reads
  (warm accept ~3.5 s with read vs ~1.5 s without). Gate suite re-run: 100%/100%.
- Stale-context: solved in the prompt — "anything you read earlier is STALE,
  re-read on EVERY request". Verified by `test_reread.py`: attribute renamed
  between two requests in one session; turn 2 issued a fresh Read and used the
  new name (`self.errorTally += 1`).
- Do NOT use `--bare`: it disables OAuth (API-key only), breaking subscription auth.
- System prompt is cached (1h ephemeral, ~1.3K tokens) — first request per session
  pays the write (~3–4 s), subsequent requests read it.

Latency (warm, this machine):

| Config              | accept (warm)  | reject        |
|---------------------|----------------|---------------|
| sonnet (default)    | 1.4–1.8 s      | 3.2–3.8 s     |
| haiku               | 5.2–9.0 s (!)  | 3.5 s         |
| sonnet --effort low | **1.4–1.6 s**  | **2.1 s**     |

→ default config: `sonnet` + `--effort low`. Haiku is slower, not faster —
the spec's two-tier model idea (haiku line tier) is dropped.

Gate behavior (model-side only, no heuristics): "make a login system" and
"parse the file and email the results" rejected with usable splits;
single-unit sentences with "and" (filter loop) correctly accepted.
