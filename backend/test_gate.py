"""Adversarial gate test (spec section 13 release gate).

Runs fixture sentences through one warm session and checks:
  - scope-bombs are rejected (release gate: >= 95%)
  - single-unit sentences are accepted
  - borderline sentences are reported but don't affect the verdict

Usage: python test_gate.py [--model sonnet] [--effort low]
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time

from nlv.prompt import RESPONSE_SCHEMA, SYSTEM_PROMPT
from nlv.protocol import ProtocolError, build_request, parse_response
from nlv.session import ClaudeSession, SessionError

MUST_REJECT = [
    "make a login system",
    "parse the file and email the results",
    "build a REST API for managing todo items",
    "implement user registration with email verification",
    "write a function that validates the form, saves the user, and sends a welcome email",
    "read the csv, clean the data, and plot a histogram",
    "add error handling to the whole module",
    "fetch the url with three retries and exponential backoff, then parse the json and store it in the db",
    "create a class that manages the database connection pool",
    "finish the rest of this function",
]

MUST_ACCEPT = [
    "increment retry_count by one",
    "assign the sum of a and b to total",
    "if the list is empty, return None",
    "loop over the orders and sum their totals into revenue",
    "define a function called parse_date that takes a string and returns a datetime",
    "break out of the loop when count exceeds limit",
    "swap the values of x and y",
    "raise a ValueError saying the id was not found",
]

BORDERLINE = [  # informational only
    "convert the name to lowercase and strip whitespace",
    "open the file and read all lines into a list",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--effort", default="low")
    args = ap.parse_args()

    session = ClaudeSession(
        cwd=".",
        system_prompt=SYSTEM_PROMPT,
        model=args.model,
        effort=args.effort,
        json_schema=RESPONSE_SCHEMA,
    )

    latencies: list[float] = []
    failures: list[str] = []

    def run(sentence: str) -> str | None:
        t0 = time.monotonic()
        try:
            turn = session.send(build_request(sentence, "python"))
            resp = parse_response(turn.result_event)
        except (SessionError, ProtocolError) as e:
            print(f"  [ERROR] {sentence!r}: {e}")
            return None
        latencies.append((time.monotonic() - t0) * 1000)
        return resp["status"]

    try:
        print(f"model={args.model} effort={args.effort}\n")

        print("scope-bombs (must reject):")
        rejected = 0
        for s in MUST_REJECT:
            status = run(s)
            mark = "PASS" if status == "rejected" else "FAIL"
            if status == "rejected":
                rejected += 1
            else:
                failures.append(f"not rejected: {s!r} -> {status}")
            print(f"  [{mark}] {s}")

        print("\nsingle units (must accept):")
        accepted = 0
        for s in MUST_ACCEPT:
            status = run(s)
            mark = "PASS" if status == "ok" else "FAIL"
            if status == "ok":
                accepted += 1
            else:
                failures.append(f"not accepted: {s!r} -> {status}")
            print(f"  [{mark}] {s}")

        print("\nborderline (informational):")
        for s in BORDERLINE:
            print(f"  [{run(s)}] {s}")

        reject_rate = rejected / len(MUST_REJECT)
        accept_rate = accepted / len(MUST_ACCEPT)
        lat = sorted(latencies)
        print(
            f"\nreject rate {rejected}/{len(MUST_REJECT)} ({reject_rate:.0%})  "
            f"accept rate {accepted}/{len(MUST_ACCEPT)} ({accept_rate:.0%})"
        )
        print(
            f"latency ms: p50 {statistics.median(lat):.0f}  "
            f"p95 {lat[max(0, int(len(lat) * 0.95) - 1)]:.0f}  max {lat[-1]:.0f}"
        )

        gate_ok = reject_rate >= 0.95
        accepts_ok = accept_rate == 1.0
        print(f"\nrelease gate (reject >= 95%): {'PASS' if gate_ok else 'FAIL'}")
        print(f"accepts (100%):               {'PASS' if accepts_ok else 'FAIL'}")
        for f in failures:
            print(f"  ! {f}")
        return 0 if (gate_ok and accepts_ok) else 1
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
