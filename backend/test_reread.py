"""Staleness test: the model must re-read the file on every request.

Sends the same sentence twice through ONE session; between the two requests the
target attribute is renamed in the file. Pass = the second response uses the
new name (proving a fresh Read, not conversation memory).
"""

from __future__ import annotations

import os
import sys

from nlv.prompt import RESPONSE_SCHEMA, SYSTEM_PROMPT
from nlv.protocol import build_request, parse_response
from nlv.session import ClaudeSession

TEMPLATE = """\
class OrderStore:
    def __init__(self):
        self.{attr} = 0

    def flushOrders(self):
        pass  # cursor: line 6
"""

TARGET = os.path.abspath("fixtures/_tmp_reread.py")
SENTENCE = "increment the failure counter attribute by one"


def turn_used_read(events: list[dict]) -> bool:
    for ev in events:
        if ev.get("type") == "assistant":
            for block in ev.get("message", {}).get("content", []):
                if block.get("type") == "tool_use" and block.get("name") == "Read":
                    return True
    return False


def main() -> int:
    session = ClaudeSession(
        cwd=".", system_prompt=SYSTEM_PROMPT, model="sonnet", effort="low",
        json_schema=RESPONSE_SCHEMA,
    )
    ok = True
    try:
        with open(TARGET, "w", encoding="utf-8") as f:
            f.write(TEMPLATE.format(attr="failedCount"))
        turn1 = session.send(build_request(SENTENCE, "python", file=TARGET, line=6))
        code1 = parse_response(turn1.result_event).get("code", "")
        print(f"turn 1 (attr=failedCount, read={turn_used_read(turn1.events)}): {code1!r}")
        if "failedCount" not in code1:
            print("  FAIL: expected failedCount")
            ok = False

        with open(TARGET, "w", encoding="utf-8") as f:
            f.write(TEMPLATE.format(attr="errorTally"))
        turn2 = session.send(build_request(SENTENCE, "python", file=TARGET, line=6))
        code2 = parse_response(turn2.result_event).get("code", "")
        used_read = turn_used_read(turn2.events)
        print(f"turn 2 (attr=errorTally,  read={used_read}): {code2!r}")
        if "errorTally" not in code2:
            print("  FAIL: stale context — expected errorTally")
            ok = False
        if not used_read:
            print("  FAIL: second turn did not use the Read tool")
            ok = False

        print("re-read test:", "PASS" if ok else "FAIL")
        return 0 if ok else 1
    finally:
        session.close()
        try:
            os.remove(TARGET)
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
