"""A fake `claude` CLI for offline lifecycle tests.

Speaks just enough stream-JSON: ignores its CLI flags, emits an init event,
then answers each user message based on keywords in the request sentence:

  (default)     -> ok, code "x = 1"
  "reject"      -> rejected with a two-step split
  "badjson"     -> garbage once; valid on the retry (REMINDER present)
  "alwaysbad"   -> garbage every time
  "toolong"     -> ok with a 20-line body
  "crashnow"    -> exit(1) without answering
  "sleepy"      -> wait 10s before answering (cancel-test target)
"""

import json
import sys
import time

sys.stdout.write(json.dumps({"type": "system", "subtype": "init", "fake": True}) + "\n")
sys.stdout.flush()


def result(payload=None, raw_text=None):
    ev = {"type": "result", "subtype": "success", "duration_ms": 1}
    if payload is not None:
        ev["structured_output"] = payload
        ev["result"] = json.dumps(payload)
    else:
        ev["result"] = raw_text
    sys.stdout.write(json.dumps(ev) + "\n")
    sys.stdout.flush()


for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    msg = json.loads(line)
    if msg.get("type") == "control_request":
        rid = msg.get("request_id")
        if msg.get("request", {}).get("subtype") == "list_models":
            body = {"subtype": "success", "request_id": rid, "response": {"models": [
                {"value": "sonnet", "displayName": "Sonnet", "description": "fake sonnet",
                 "supportedEffortLevels": ["low", "medium", "high"]},
                {"value": "opus", "displayName": "Opus", "description": "fake opus",
                 "supportedEffortLevels": ["low", "high", "max"]},
            ]}}
        else:
            body = {"subtype": "error", "request_id": rid,
                    "error": f"Unsupported control request subtype: {msg['request'].get('subtype')}"}
        sys.stdout.write(json.dumps({"type": "control_response", "response": body}) + "\n")
        sys.stdout.flush()
        continue
    text = msg["message"]["content"][0]["text"]
    try:
        sentence = json.loads(text.split("\n\nREMINDER")[0])["sentence"]
    except (json.JSONDecodeError, KeyError):
        sentence = text
    is_retry = "REMINDER" in text

    if "needsread" in sentence:
        # skips the Read on the first ask; reads when reminded
        if is_retry:
            sys.stdout.write(json.dumps({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Read", "input": {"file_path": "x"}}]}}) + "\n")
            sys.stdout.flush()
            result({"status": "ok", "code": "read = True"})
        else:
            result({"status": "ok", "code": "unread = True"})
    elif "neverread" in sentence:
        result({"status": "ok", "code": "unread = True"})
    elif "crashnow" in sentence:
        sys.exit(1)
    elif "sleepy" in sentence:
        time.sleep(10)
        result({"status": "ok", "code": "slept = True"})
    elif "alwaysbad" in sentence:
        result(raw_text="definitely { not json")
    elif "badjson" in sentence:
        if is_retry:
            result({"status": "ok", "code": "retried = True"})
        else:
            result(raw_text="oops here is some prose")
    elif "toolong" in sentence:
        result({"status": "ok", "code": "\n".join(f"line_{i} = {i}" for i in range(20))})
    elif "reject" in sentence:
        result({"status": "rejected", "message": "Don't be a viber!",
                "split": ["do the first thing", "do the second thing"]})
    else:
        result({"status": "ok", "code": "x = 1"})
