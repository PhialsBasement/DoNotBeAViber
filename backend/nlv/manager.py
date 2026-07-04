"""SessionManager: lifecycle + policy around one warm ClaudeSession.

- lazy spawn, idle-timeout kill, crash -> one auto-respawn then error
- cancel = hard kill (next request respawns; costs one cache re-write)
- one silent retry on malformed output, with a JSON-only reminder (spec s13)
- over-scope guard: accepted code longer than max_lines is refused (spec s13)
- logs reject_gate / over_scope / error events; accept/discard are the
  frontend's to report (it knows the final outcome)
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from .log import JsonlLogger
from .prompt import RESPONSE_SCHEMA, SYSTEM_PROMPT
from .protocol import ProtocolError, build_request, parse_response
from .session import ClaudeSession, SessionDead, SessionError

JSON_REMINDER = (
    "\n\nREMINDER: Respond with ONLY the JSON object matching the required "
    "schema. No prose, no fences."
)

READ_REFUSAL = (
    "\n\nYOUR PREVIOUS ANSWER WAS REJECTED AND DISCARDED — reason: you returned "
    'status "ok" WITHOUT using the Read tool on the file this turn. Unread '
    "answers are never accepted, no matter how correct they look. Use the Read "
    "tool on {file} around line {line} NOW, then answer the request again."
)


class Cancelled(SessionError):
    pass


class OverScope(SessionError):
    pass


class ReadSkipped(SessionError):
    """Model returned ok for a file-backed request without ever reading the file."""


def _turn_used_read(events: list) -> bool:
    for ev in events:
        if ev.get("type") == "assistant":
            for block in ev.get("message", {}).get("content", []):
                if block.get("type") == "tool_use" and block.get("name") == "Read":
                    return True
    return False


@dataclass
class ManagerConfig:
    cwd: str = "."
    model: str = "sonnet"
    effort: str | None = "low"
    timeout_s: float = 60.0
    idle_s: float = 900.0
    max_lines: int = 10
    reap_interval_s: float = 15.0
    exe: str | list[str] | None = None  # override for tests (fake claude)
    tools: tuple[str, ...] = ("Read",)


class SessionManager:
    def __init__(self, config: ManagerConfig, logger: JsonlLogger | None = None):
        self.config = config
        self.logger = logger
        self._session: ClaudeSession | None = None
        self._lock = threading.RLock()
        self._last_used = time.monotonic()
        self._cancelled = False
        self._stop = threading.Event()
        threading.Thread(target=self._reap_idle, daemon=True).start()

    # -- internals -----------------------------------------------------------

    def _log(self, event: str, **fields):
        if self.logger:
            try:
                self.logger.log(event, **fields)
            except OSError:
                pass  # logging must never break a translation

    def _spawn(self) -> ClaudeSession:
        c = self.config
        return ClaudeSession(
            cwd=c.cwd,
            system_prompt=SYSTEM_PROMPT,
            model=c.model,
            effort=c.effort,
            json_schema=RESPONSE_SCHEMA,
            tools=c.tools,
            timeout_s=c.timeout_s,
            exe=c.exe,
        )

    def _ensure(self) -> ClaudeSession:
        with self._lock:
            if self._session is None or not self._session.alive:
                self._session = self._spawn()
            self._last_used = time.monotonic()
            return self._session

    def _reap_idle(self):
        while not self._stop.wait(self.config.reap_interval_s):
            with self._lock:
                if (
                    self._session is not None
                    and time.monotonic() - self._last_used > self.config.idle_s
                ):
                    self._session.close()
                    self._session = None

    # -- public api ----------------------------------------------------------

    @property
    def session_alive(self) -> bool:
        with self._lock:
            return self._session is not None and self._session.alive

    def translate(
        self,
        sentence: str,
        language_id: str,
        file: str | None = None,
        line: int | None = None,
        indent: str = "",
    ) -> dict:
        self._cancelled = False
        req = build_request(sentence, language_id, file=file, line=line, indent=indent)
        text = req
        respawn_left = 1
        json_retry_left = 1  # one silent retry on malformed output (spec s13)
        started = time.monotonic()  # unread answers are refused for as long as the request lives

        while True:
            # send, with one respawn on a dead session
            while True:
                session = self._ensure()
                try:
                    turn = session.send(text)
                    break
                except SessionDead:
                    if self._cancelled:
                        raise Cancelled("request cancelled")
                    if respawn_left > 0:
                        respawn_left -= 1
                        continue
                    self._log("error", error="session_dead", sentence=sentence)
                    raise
            with self._lock:
                self._last_used = time.monotonic()

            try:
                resp = parse_response(turn.result_event)
            except ProtocolError as e:
                if json_retry_left > 0:
                    json_retry_left -= 1
                    text = req + JSON_REMINDER
                    continue
                self._log("error", error="protocol", detail=str(e), sentence=sentence)
                raise

            if resp["status"] == "ok":
                # hard guarantee: an ok for a file-backed request is NEVER
                # accepted unless the model read the file this request. Each
                # unread answer is discarded with an explicit reason; we keep
                # forcing until it complies or the request's time is up.
                if file is not None and not _turn_used_read(turn.events):
                    if time.monotonic() - started < self.config.timeout_s:
                        text += READ_REFUSAL.format(file=file, line=line)
                        continue
                    self._log("error", error="read_skipped", sentence=sentence, file=file)
                    raise ReadSkipped(
                        f"not accepted: the model kept answering without reading {file} — "
                        f"every unread answer was discarded for "
                        f"{time.monotonic() - started:.0f}s until the request timed out"
                    )
                n_lines = len(resp["code"].strip().splitlines())
                if n_lines > self.config.max_lines:
                    self._log(
                        "over_scope",
                        sentence=sentence,
                        languageId=language_id,
                        lines=n_lines,
                        generated=resp["code"],
                        file=file,
                    )
                    raise OverScope(
                        f"model returned {n_lines} lines (max {self.config.max_lines}) — "
                        "likely over-helping; try a narrower sentence"
                    )
                return resp

            self._log(
                "reject_gate",
                sentence=sentence,
                languageId=language_id,
                split=resp["split"],
                file=file,
            )
            return resp

    def list_models(self) -> list:
        """Ask the warm session which models this Claude Code install offers."""
        session = self._ensure()
        resp = session.control("list_models")
        with self._lock:
            self._last_used = time.monotonic()
        models = resp.get("models")
        return models if isinstance(models, list) else []

    def cancel(self):
        """Kill the in-flight request. Next request respawns lazily."""
        with self._lock:
            self._cancelled = True
            if self._session is not None:
                self._session.kill()
                self._session = None

    def restart(self):
        with self._lock:
            if self._session is not None:
                self._session.close()
                self._session = None

    def close(self):
        self._stop.set()
        self.restart()
