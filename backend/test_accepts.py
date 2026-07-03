"""False-rejection sweep: legitimate single-unit sentences that MUST pass.

Counterweight to the referent rule in the gate — run after any prompt change
that makes the gate stricter. All sentences run with file context, the way the
extension actually sends them.

Usage: python test_accepts.py [--model sonnet] [--effort low]
"""

from __future__ import annotations

import argparse
import os
import sys
import time

from nlv.prompt import RESPONSE_SCHEMA, SYSTEM_PROMPT
from nlv.protocol import ProtocolError, build_request, parse_response
from nlv.session import ClaudeSession, SessionError

PY_CTX = os.path.abspath("fixtures/gate_context.py")   # orders, items, retry_count, a, b, x, y, count, limit, revenue
JS_CTX = os.path.abspath("fixtures/gate_context.js")   # queue, user, config, results, item, retryCount, subtotal

# (sentence, languageId, ctx file, cursor line)
MUST_ACCEPT = [
    # pronouns / articles binding to file contents
    ("append the entry to the results list",                          "javascript", JS_CTX, 6),
    ("loop over the orders and print each one",                       "python", PY_CTX, 12),
    ("raise a KeyError using the entry as the message",               "python", PY_CTX, 12),
    ("log the config object to the console",                          "javascript", JS_CTX, 6),
    ("delete the first element of items",                             "python", PY_CTX, 12),
    # fresh names introduced by the sentence itself
    ("create an empty dictionary called cache",                       "python", PY_CTX, 12),
    ("assign the larger of a and b to a variable called winner",      "python", PY_CTX, 12),
    ("declare a constant called MAX_RETRIES set to five",             "javascript", JS_CTX, 6),
    ("make a list called processed containing only the even numbers from items", "python", PY_CTX, 12),
    ("make an arrow function called double that returns its argument times two", "javascript", JS_CTX, 6),
    # single units that contain "and" (must not be mistaken for two operations)
    ("convert x to uppercase and strip whitespace",                   "python", PY_CTX, 12),
    ("loop over the queue and add each entry's price to subtotal",    "javascript", JS_CTX, 6),
    # guards / conditions / simple statements
    ("if revenue exceeds limit, break out of the loop",               "python", PY_CTX, 12),
    ("if retry_count exceeds limit, return True",                     "python", PY_CTX, 12),
    ("if the user has no id property, throw an Error saying missing id", "javascript", JS_CTX, 6),
    ("set count to zero",                                             "python", PY_CTX, 12),
    ("increment retryCount",                                          "javascript", JS_CTX, 6),
    ("return true if subtotal is zero",                               "javascript", JS_CTX, 6),
    ("return the sum of a and b",                                     "python", PY_CTX, 12),
    ("define a function called flush_cache that takes no arguments",  "python", PY_CTX, 12),
]

BORDERLINE = [  # informational only — reasonable people could rule either way
    ("wrap the call to process_batch in a try that returns None on ValueError", "python", PY_CTX, 12),
    ("swap x and y without a temporary variable",                     "python", PY_CTX, 12),
    ("sort items in place by price, descending",                      "python", PY_CTX, 12),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--effort", default="low")
    args = ap.parse_args()

    session = ClaudeSession(
        cwd=".", system_prompt=SYSTEM_PROMPT, model=args.model,
        effort=args.effort, json_schema=RESPONSE_SCHEMA,
    )
    failures = []
    t_start = time.monotonic()
    try:
        print(f"model={args.model} effort={args.effort}\n\nmust accept:")
        for sentence, lang, ctx, line in MUST_ACCEPT:
            try:
                turn = session.send(build_request(sentence, lang, file=ctx, line=line))
                resp = parse_response(turn.result_event)
            except (SessionError, ProtocolError) as e:
                failures.append((sentence, f"error: {e}"))
                print(f"  [ERR ] {sentence}")
                continue
            if resp["status"] == "ok":
                print(f"  [PASS] {sentence}")
            else:
                failures.append((sentence, "rejected: " + " | ".join(resp["split"])))
                print(f"  [FAIL] {sentence}")

        print("\nborderline (informational):")
        for sentence, lang, ctx, line in BORDERLINE:
            try:
                turn = session.send(build_request(sentence, lang, file=ctx, line=line))
                resp = parse_response(turn.result_event)
                print(f"  [{resp['status']}] {sentence}")
            except (SessionError, ProtocolError) as e:
                print(f"  [ERR] {sentence}: {e}")

        n = len(MUST_ACCEPT)
        print(f"\naccepted {n - len(failures)}/{n} in {time.monotonic() - t_start:.0f}s")
        for s, why in failures:
            print(f"  ! {s!r} -> {why}")
        print("false-rejection sweep:", "PASS" if not failures else "FAIL")
        return 1 if failures else 0
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
