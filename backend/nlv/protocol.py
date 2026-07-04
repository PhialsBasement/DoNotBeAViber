"""Request payload construction and strict response validation (spec section 8).

Nothing non-conforming ever reaches an insert: parse failures raise
ProtocolError and the caller decides on the one silent retry.
"""

from __future__ import annotations

import json


class ProtocolError(Exception):
    def __init__(self, msg: str, raw: str = ""):
        super().__init__(msg)
        self.raw = raw


def build_request(
    sentence: str,
    language_id: str,
    file: str | None = None,
    line: int | None = None,
    indent: str = "",
) -> str:
    return json.dumps(
        {
            "sentence": sentence,
            "languageId": language_id,
            "file": file,
            "line": line,
            "indent": indent,
        },
        ensure_ascii=False,
    )


def build_question(
    question: str,
    language_id: str,
    file: str | None = None,
    line: int | None = None,
) -> str:
    return json.dumps(
        {"question": question, "languageId": language_id, "file": file, "line": line},
        ensure_ascii=False,
    )


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        first_nl = text.find("\n")
        if first_nl != -1 and text.rstrip().endswith("```"):
            text = text[first_nl + 1 : text.rstrip().rfind("```")]
    return text.strip()


def parse_response(result_event: dict) -> dict:
    """Validate a turn's result event into {"status": "ok"|"rejected", ...}."""
    if result_event.get("subtype") not in (None, "success"):
        raise ProtocolError(
            f"claude turn errored: {result_event.get('subtype')}",
            json.dumps(result_event)[:2000],
        )

    payload = result_event.get("structured_output")
    if payload is None:
        raw = result_event.get("result", "")
        if not isinstance(raw, str) or not raw.strip():
            raise ProtocolError("empty result from model", json.dumps(result_event)[:2000])
        try:
            payload = json.loads(_strip_fences(raw))
        except json.JSONDecodeError as e:
            raise ProtocolError(f"model output is not JSON: {e}", raw)

    if not isinstance(payload, dict):
        raise ProtocolError("model output is not a JSON object", str(payload))

    status = payload.get("status")
    if status == "ok":
        code = payload.get("code")
        if not isinstance(code, str) or not code.strip():
            raise ProtocolError("status=ok but 'code' missing/empty", json.dumps(payload))
        # defense: model occasionally nests its whole JSON answer inside `code`
        stripped = code.strip()
        if stripped.startswith("{") and '"status"' in stripped:
            try:
                inner = json.loads(stripped)
                if (
                    isinstance(inner, dict)
                    and inner.get("status") == "ok"
                    and isinstance(inner.get("code"), str)
                    and inner["code"].strip()
                ):
                    code = inner["code"]
            except json.JSONDecodeError:
                pass
        return {"status": "ok", "code": code}
    if status == "rejected":
        message = payload.get("message")
        split = payload.get("split")
        if not isinstance(message, str):
            raise ProtocolError("status=rejected but 'message' missing", json.dumps(payload))
        if not isinstance(split, list) or not all(isinstance(s, str) for s in split):
            raise ProtocolError("status=rejected but 'split' missing/invalid", json.dumps(payload))
        return {"status": "rejected", "message": message, "split": split}
    if status == "answered":
        answer = payload.get("answer")
        if not isinstance(answer, str) or not answer.strip():
            raise ProtocolError("status=answered but 'answer' missing/empty", json.dumps(payload))
        return {"status": "answered", "answer": answer}
    if status == "refused":
        message = payload.get("message")
        if not isinstance(message, str) or not message.strip():
            raise ProtocolError("status=refused but 'message' missing/empty", json.dumps(payload))
        return {"status": "refused", "message": message}

    raise ProtocolError(f"unknown status: {status!r}", json.dumps(payload))
