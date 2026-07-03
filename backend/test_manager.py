"""Offline SessionManager lifecycle tests against fake_claude.py. Fast, free.

Usage: python test_manager.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time

from nlv.log import JsonlLogger
from nlv.manager import Cancelled, ManagerConfig, OverScope, SessionManager
from nlv.protocol import ProtocolError
from nlv.session import SessionError

FAKE = [sys.executable, os.path.abspath("fake_claude.py")]

results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = ""):
    results.append((name, cond, detail))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail and not cond else ""))


def make_manager(ws: str, **overrides) -> SessionManager:
    cfg = ManagerConfig(cwd=ws, exe=FAKE, timeout_s=8.0, reap_interval_s=0.2, **overrides)
    return SessionManager(cfg, logger=JsonlLogger(ws))


def main() -> int:
    ws = tempfile.mkdtemp(prefix="nlv_test_")
    m = make_manager(ws)
    try:
        # 1. normal translate
        r = m.translate("set x to one", "python")
        check("translate ok", r == {"status": "ok", "code": "x = 1"}, str(r))

        # 2. reject path + reject_gate logged
        r = m.translate("reject this please", "python")
        check("translate rejected", r["status"] == "rejected" and len(r["split"]) == 2, str(r))

        # 3. malformed once -> silent retry succeeds
        r = m.translate("badjson please", "python")
        check("retry on malformed json", r == {"status": "ok", "code": "retried = True"}, str(r))

        # 4. malformed twice -> ProtocolError
        try:
            m.translate("alwaysbad please", "python")
            check("protocol error after 2 bad", False, "no exception")
        except ProtocolError:
            check("protocol error after 2 bad", True)

        # 5. over-scope guard
        try:
            m.translate("toolong please", "python")
            check("over-scope refused", False, "no exception")
        except OverScope:
            check("over-scope refused", True)

        # 6. crash -> one respawn -> crash again -> SessionError
        try:
            m.translate("crashnow", "python")
            check("session dead after crash+respawn", False, "no exception")
        except SessionError:
            check("session dead after crash+respawn", True)

        # 7. respawn after external death: works again
        r = m.translate("set x to one", "python")
        check("respawn after crash", r["status"] == "ok", str(r))

        # 8. cancel mid-flight
        errbox: dict = {}

        def slow():
            try:
                m.translate("sleepy request", "python")
                errbox["exc"] = None
            except Exception as e:
                errbox["exc"] = e

        t = threading.Thread(target=slow)
        t.start()
        time.sleep(0.8)  # let it get in flight
        m.cancel()
        t.join(timeout=10)
        check("cancel raises Cancelled", isinstance(errbox.get("exc"), Cancelled), repr(errbox.get("exc")))

        # 9. idle reap
        m2 = make_manager(ws, idle_s=0.5)
        m2.translate("set x to one", "python")
        check("session alive after use", m2.session_alive)
        time.sleep(1.2)
        check("idle session reaped", not m2.session_alive)
        r = m2.translate("set x to one", "python")
        check("lazy respawn after reap", r["status"] == "ok", str(r))
        m2.close()

        # 10. log file contents
        log_path = os.path.join(ws, ".nlv", "log.jsonl")
        events = [json.loads(l)["event"] for l in open(log_path, encoding="utf-8")]
        check("reject_gate logged", "reject_gate" in events, str(events))
        check("over_scope logged", "over_scope" in events, str(events))
        check(".nlv gitignored", os.path.exists(os.path.join(ws, ".nlv", ".gitignore")))
    finally:
        m.close()

    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
