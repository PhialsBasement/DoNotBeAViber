"""CLI harness for the warm-session backend. No VS Code anywhere.

Usage:
  python harness.py --once "loop over users and keep the active ones"
  python harness.py                      # REPL: one sentence per line
  python harness.py --raw --once "..."  # dump every stream event

REPL commands:  :lang <id>   switch language (default python)
                :q           quit
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from nlv.prompt import RESPONSE_SCHEMA, SYSTEM_PROMPT
from nlv.protocol import ProtocolError, build_request, parse_response
from nlv.session import ClaudeSession, SessionError


def run_turn(
    session: ClaudeSession,
    sentence: str,
    lang: str,
    raw: bool,
    file: str | None = None,
    line: int | None = None,
) -> None:
    req = build_request(sentence, lang, file=file, line=line)
    t0 = time.monotonic()
    turn = session.send(req)
    ms = (time.monotonic() - t0) * 1000

    if raw:
        for ev in turn.events:
            print(json.dumps(ev, indent=2)[:4000])

    try:
        resp = parse_response(turn.result_event)
    except ProtocolError as e:
        print(f"[protocol error after {ms:.0f} ms] {e}")
        if e.raw:
            print(f"  raw: {e.raw[:500]}")
        return

    if resp["status"] == "ok":
        print(f"[ok, {ms:.0f} ms]")
        print(resp["code"])
    else:
        print(f"[rejected, {ms:.0f} ms] {resp['message']}")
        for s in resp["split"]:
            print(f"  - {s}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", help="translate one sentence and exit")
    ap.add_argument("--lang", default="python")
    ap.add_argument("--file", default=None, help="target file the model may Read for context")
    ap.add_argument("--line", type=int, default=None, help="cursor line in --file (1-based)")
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--effort", default=None, help="low|medium|high|xhigh|max")
    ap.add_argument("--raw", action="store_true", help="dump all stream events")
    ap.add_argument("--no-schema", action="store_true", help="skip --json-schema flag")
    args = ap.parse_args()

    print(f"spawning warm session (model={args.model})...")
    t0 = time.monotonic()
    try:
        session = ClaudeSession(
            cwd=".",
            system_prompt=SYSTEM_PROMPT,
            model=args.model,
            effort=args.effort,
            json_schema=None if args.no_schema else RESPONSE_SCHEMA,
        )
    except SessionError as e:
        print(f"error: {e}")
        return 1
    print(f"process spawned in {(time.monotonic() - t0) * 1000:.0f} ms (warmup completes on first request)")

    try:
        if args.once:
            run_turn(session, args.once, args.lang, args.raw, args.file, args.line)
            return 0

        lang = args.lang
        file, cursor = args.file, args.line
        print(f"language: {lang} — :lang <id>, :file <path> [line], :q to quit")
        while True:
            try:
                entry = input(f"{lang}> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not entry:
                continue
            if entry == ":q":
                break
            if entry.startswith(":lang "):
                lang = entry.split(None, 1)[1].strip()
                continue
            if entry.startswith(":file "):
                parts = entry.split()
                file = parts[1]
                cursor = int(parts[2]) if len(parts) > 2 else None
                continue
            try:
                run_turn(session, entry, lang, args.raw, file, cursor)
            except SessionError as e:
                print(f"session error: {e}")
                return 1
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
