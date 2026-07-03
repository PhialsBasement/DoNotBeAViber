"""End-to-end daemon test: drives server.py over stdio NDJSON like VS Code will.

Uses fake_claude.py — offline, fast, free.  Usage: python test_server.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time

results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = ""):
    results.append((name, cond, detail))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail and not cond else ""))


def main() -> int:
    ws = tempfile.mkdtemp(prefix="nlv_srv_")
    exe_arg = f"{sys.executable}|{os.path.abspath('fake_claude.py')}"
    proc = subprocess.Popen(
        [sys.executable, "server.py", "--workspace", ws, "--exe", exe_arg, "--timeout", "8"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", bufsize=1,
    )
    responses: dict = {}

    def reader():
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if line:
                try:
                    msg = json.loads(line)
                    responses[msg.get("id")] = msg
                except json.JSONDecodeError:
                    responses.setdefault("_garbage", []).append(line)

    threading.Thread(target=reader, daemon=True).start()

    def send(rid, method, params=None):
        req = {"id": rid, "method": method}
        if params is not None:
            req["params"] = params
        assert proc.stdin is not None
        proc.stdin.write(json.dumps(req) + "\n")
        proc.stdin.flush()

    def wait(rid, timeout=15.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if rid in responses:
                return responses.pop(rid)
            time.sleep(0.02)
        return None

    try:
        # 1. status before any work
        send(1, "status")
        r = wait(1)
        check("status", r is not None and r["ok"] and r["result"]["sessionAlive"] is False, str(r))

        # 2. translate ok
        send(2, "translate", {"sentence": "set x to one", "languageId": "python"})
        r = wait(2)
        check("translate ok", r and r["ok"] and r["result"] == {"status": "ok", "code": "x = 1"}, str(r))

        # 3. translate rejected
        send(3, "translate", {"sentence": "reject this", "languageId": "python"})
        r = wait(3)
        check("translate rejected", r and r["ok"] and r["result"]["status"] == "rejected", str(r))

        # 4. busy while in flight, then cancel
        send(4, "translate", {"sentence": "sleepy request", "languageId": "python"})
        time.sleep(0.8)  # let it get in flight
        send(5, "translate", {"sentence": "set x to one", "languageId": "python"})
        r5 = wait(5)
        check("busy rejected", r5 and not r5["ok"] and r5["error"]["code"] == "busy", str(r5))
        send(6, "cancel")
        r6 = wait(6)
        r4 = wait(4)
        check("cancel acked", r6 is not None and r6["ok"], str(r6))
        check("in-flight cancelled", r4 and not r4["ok"] and r4["error"]["code"] == "cancelled", str(r4))

        # 5. works again after cancel (lazy respawn)
        send(7, "translate", {"sentence": "set x to one", "languageId": "python"})
        r = wait(7)
        check("respawn after cancel", r and r["ok"] and r["result"]["status"] == "ok", str(r))

        # 6. empty sentence -> bad-request (the only local input check)
        send(8, "translate", {"sentence": "   ", "languageId": "python"})
        r = wait(8)
        check("empty sentence bad-request", r and not r["ok"] and r["error"]["code"] == "bad-request", str(r))

        # 6b. list models via control protocol
        send(12, "models")
        r = wait(12)
        check("models listed",
              r and r["ok"] and [m["value"] for m in r["result"]["models"]] == ["sonnet", "opus"],
              str(r))

        # 7. logEvent from the frontend
        send(9, "logEvent", {"event": "accept", "languageId": "python",
                             "sentence": "set x to one", "final": "x = 1"})
        r = wait(9)
        check("logEvent acked", r is not None and r["ok"], str(r))

        # 8. shutdown
        send(10, "shutdown")
        r = wait(10)
        check("shutdown acked", r is not None and r["ok"], str(r))
        proc.wait(timeout=10)
        check("daemon exited", proc.poll() is not None)

        events = [json.loads(l)["event"] for l in open(os.path.join(ws, ".nlv", "log.jsonl"), encoding="utf-8")]
        check("accept + reject_gate in log", "accept" in events and "reject_gate" in events, str(events))
    finally:
        if proc.poll() is None:
            proc.kill()

    failed = [x for x in results if not x[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    if proc.stderr and failed:
        print("daemon stderr:", proc.stderr.read()[:2000])
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
