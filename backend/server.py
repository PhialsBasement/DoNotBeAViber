"""The daemon VS Code talks to. NDJSON over stdio, language-server style.

  python server.py --workspace <root> [--model sonnet] [--effort low] ...

Requests  (one JSON object per line on stdin):
  {"id": 1, "method": "translate", "params": {"sentence", "languageId",
                                              "file"?, "line"?, "indent"?}}
  {"id": 2, "method": "cancel"}
  {"id": 3, "method": "restart"}
  {"id": 4, "method": "status"}
  {"id": 5, "method": "logEvent", "params": {"event": "accept", ...}}
  {"id": 6, "method": "shutdown"}

Responses (one per request, any order):
  {"id": 1, "ok": true,  "result": {"status": "ok", "code": "..."}}
  {"id": 1, "ok": true,  "result": {"status": "rejected", "message": "...", "split": [...]}}
  {"id": 1, "ok": false, "error": {"code": "over-scope"|"cancelled"|"timeout"|
                                   "protocol"|"claude-not-found"|"session-dead"|
                                   "busy"|"bad-request", "message": "..."}}

One translate in flight at a time (spec: one keypress per generation);
cancel/status/restart are handled immediately.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading

from nlv.log import JsonlLogger
from nlv.manager import Cancelled, ManagerConfig, OverScope, ReadSkipped, SessionManager
from nlv.protocol import ProtocolError
from nlv.session import ClaudeNotFound, RequestTimeout, SessionError


def main() -> int:
    # Windows defaults stdio to the locale codec (cp1252) — force UTF-8 so code
    # content survives; utf-8-sig also swallows a client-sent BOM.
    sys.stdin.reconfigure(encoding="utf-8-sig")
    sys.stdout.reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--effort", default="low")
    ap.add_argument("--timeout", type=float, default=60.0)
    ap.add_argument("--idle-minutes", type=float, default=15.0)
    ap.add_argument("--max-lines", type=int, default=10)
    ap.add_argument("--exe", default=None, help=argparse.SUPPRESS)  # tests: fake claude
    args = ap.parse_args()

    exe = None
    if args.exe:  # "python|C:\path\fake_claude.py" or a plain path
        exe = args.exe.split("|") if "|" in args.exe else args.exe

    logger = JsonlLogger(args.workspace)
    manager = SessionManager(
        ManagerConfig(
            cwd=args.workspace,
            model=args.model,
            effort=args.effort or None,
            timeout_s=args.timeout,
            idle_s=args.idle_minutes * 60,
            max_lines=args.max_lines,
            exe=exe,
        ),
        logger=logger,
    )

    out_lock = threading.Lock()

    def respond(rid, ok: bool, payload: dict):
        msg = {"id": rid, "ok": ok, ("result" if ok else "error"): payload}
        with out_lock:
            sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
            sys.stdout.flush()

    def err(rid, code: str, message: str):
        respond(rid, False, {"code": code, "message": message})

    busy = threading.Event()
    inflight = {"n": 0}
    inflight_lock = threading.Lock()

    def track(delta: int):
        with inflight_lock:
            inflight["n"] += delta

    def do_translate(rid, params: dict, method: str = "translate"):
        try:
            if method == "ask":
                question = (params.get("question") or "").strip()
                if not question:
                    err(rid, "bad-request", "empty question")
                    return
                result = manager.ask(
                    question,
                    params.get("languageId", "plaintext"),
                    file=params.get("file"),
                    line=params.get("line"),
                )
                respond(rid, True, result)
                return
            sentence = (params.get("sentence") or "").strip()
            if not sentence:
                err(rid, "bad-request", "empty sentence")  # the only local input check
                return
            result = manager.translate(
                sentence,
                params.get("languageId", "plaintext"),
                file=params.get("file"),
                line=params.get("line"),
                indent=params.get("indent", ""),
            )
            respond(rid, True, result)
        except Cancelled as e:
            err(rid, "cancelled", str(e))
        except OverScope as e:
            err(rid, "over-scope", str(e))
        except ReadSkipped as e:
            err(rid, "no-read", str(e))
        except ClaudeNotFound as e:
            err(rid, "claude-not-found", str(e))
        except RequestTimeout as e:
            err(rid, "timeout", str(e))
        except ProtocolError as e:
            err(rid, "protocol", str(e))
        except SessionError as e:
            err(rid, "session-dead", str(e))
        except Exception as e:  # never let the daemon die on one request
            err(rid, "internal", f"{type(e).__name__}: {e}")
        finally:
            busy.clear()
            track(-1)

    try:
        for raw in sys.stdin:
            raw = raw.lstrip("﻿").strip()  # per-line BOM guard
            if not raw:
                continue
            try:
                req = json.loads(raw)
                rid = req.get("id")
                method = req.get("method")
                params = req.get("params") or {}
            except (json.JSONDecodeError, AttributeError):
                respond(None, False, {"code": "bad-request", "message": f"unparseable: {raw[:200]}"})
                continue

            if method in ("translate", "ask"):
                if busy.is_set():
                    err(rid, "busy", "a request is already in flight")
                    continue
                busy.set()
                track(1)
                threading.Thread(target=do_translate, args=(rid, params, method), daemon=True).start()
            elif method == "models":
                def do_models(rid=rid):
                    try:
                        respond(rid, True, {"models": manager.list_models()})
                    except SessionError as e:
                        err(rid, "session-dead", str(e))
                    except Exception as e:
                        err(rid, "internal", f"{type(e).__name__}: {e}")
                    finally:
                        track(-1)
                track(1)
                threading.Thread(target=do_models, daemon=True).start()
            elif method == "cancel":
                manager.cancel()
                respond(rid, True, {})
            elif method == "restart":
                manager.restart()
                respond(rid, True, {})
            elif method == "status":
                respond(rid, True, {
                    "sessionAlive": manager.session_alive,
                    "busy": busy.is_set(),
                    "model": args.model,
                    "effort": args.effort,
                })
            elif method == "logEvent":
                event = params.pop("event", None)
                if not event:
                    err(rid, "bad-request", "logEvent needs 'event'")
                else:
                    logger.log(event, **params)
                    respond(rid, True, {})
            elif method == "shutdown":
                manager.cancel()  # in-flight request gets a "cancelled" response
                respond(rid, True, {})
                break
            else:
                err(rid, "bad-request", f"unknown method: {method}")
    finally:
        # stdin EOF with work in flight: let workers finish and write their
        # responses before tearing the session down
        deadline = args.timeout + 5.0
        pause = threading.Event()
        waited = 0.0
        while inflight["n"] > 0 and waited < deadline:
            pause.wait(0.1)
            waited += 0.1
        manager.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
