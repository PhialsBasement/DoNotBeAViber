"""Warm claude CLI session: one long-lived process, stream-JSON over stdio.

Spawns `claude -p --input-format stream-json --output-format stream-json` and
keeps it alive across requests. One request in flight at a time (the extension
is single-user, one keypress per generation).
"""

from __future__ import annotations

import json
import queue
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field


class SessionError(Exception):
    pass


class ClaudeNotFound(SessionError):
    """claude binary missing from PATH — surface install instructions, never auth."""


class SessionDead(SessionError):
    def __init__(self, msg: str, stderr_tail: str = ""):
        super().__init__(msg + (f"\n--- claude stderr ---\n{stderr_tail}" if stderr_tail else ""))
        self.stderr_tail = stderr_tail


class RequestTimeout(SessionError):
    pass


@dataclass
class TurnResult:
    result_event: dict
    events: list[dict] = field(default_factory=list)
    elapsed_s: float = 0.0


class ClaudeSession:
    def __init__(
        self,
        cwd: str,
        system_prompt: str,
        model: str = "sonnet",
        effort: str | None = None,
        json_schema: dict | None = None,
        tools: tuple[str, ...] = ("Read",),
        timeout_s: float = 60.0,
        exe: str | list[str] | None = None,
    ):
        if exe is None:
            found = shutil.which("claude")
            if found is None:
                raise ClaudeNotFound(
                    "The 'claude' CLI was not found on PATH. Install Claude Code and log in: "
                    "https://claude.com/claude-code"
                )
            exe_list = [found]
        else:
            exe_list = [exe] if isinstance(exe, str) else list(exe)
        args = [
            *exe_list,
            "-p",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--verbose",
            "--model", model,
            "--system-prompt", system_prompt,
            "--tools", ",".join(tools),    # read-only context gathering ("" = none)
            "--no-session-persistence",    # nothing written to disk
            "--strict-mcp-config",         # no MCP servers
            "--disable-slash-commands",    # no skills
        ]
        if effort is not None:
            args += ["--effort", effort]
        if json_schema is not None:
            args += ["--json-schema", json.dumps(json_schema, separators=(",", ":"))]

        self.timeout_s = timeout_s
        self._lock = threading.Lock()
        self._events: queue.Queue[dict | None] = queue.Queue()
        self._stderr_lines: list[str] = []
        self._closed = False
        self._dead = False  # set on stdout EOF / write failure; poll() can lag
        self.spawned_at = time.monotonic()

        self.proc = subprocess.Popen(
            args,
            cwd=cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    # -- io threads ---------------------------------------------------------

    def _read_stdout(self):
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                self._events.put(json.loads(line))
            except json.JSONDecodeError:
                self._events.put({"type": "_unparseable", "raw": line})
        self._dead = True
        self._events.put(None)  # EOF sentinel

    def _read_stderr(self):
        assert self.proc.stderr is not None
        for line in self.proc.stderr:
            self._stderr_lines.append(line.rstrip())
            if len(self._stderr_lines) > 50:
                del self._stderr_lines[0]

    # -- public api ----------------------------------------------------------

    @property
    def alive(self) -> bool:
        return not self._closed and not self._dead and self.proc.poll() is None

    def stderr_tail(self) -> str:
        return "\n".join(self._stderr_lines[-15:])

    def send(self, text: str, timeout_s: float | None = None) -> TurnResult:
        """Send one user message; block until the turn's `result` event."""
        timeout_s = timeout_s or self.timeout_s
        with self._lock:
            if not self.alive:
                raise SessionDead("claude process is not running", self.stderr_tail())
            msg = {
                "type": "user",
                "message": {"role": "user", "content": [{"type": "text", "text": text}]},
            }
            start = time.monotonic()
            try:
                assert self.proc.stdin is not None
                self.proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
                self.proc.stdin.flush()
            except OSError as e:
                self._dead = True
                raise SessionDead(f"failed writing to claude stdin: {e}", self.stderr_tail())

            events: list[dict] = []
            deadline = start + timeout_s
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RequestTimeout(f"no result after {timeout_s:.0f}s")
                try:
                    ev = self._events.get(timeout=min(remaining, 1.0))
                except queue.Empty:
                    continue
                if ev is None:
                    raise SessionDead("claude process exited mid-request", self.stderr_tail())
                events.append(ev)
                if ev.get("type") == "result":
                    return TurnResult(ev, events, time.monotonic() - start)

    def control(self, subtype: str, timeout_s: float = 15.0) -> dict:
        """Send a stream-json control request (e.g. list_models); return its response."""
        with self._lock:
            if not self.alive:
                raise SessionDead("claude process is not running", self.stderr_tail())
            rid = f"ctl-{time.monotonic_ns()}"
            msg = {"type": "control_request", "request_id": rid, "request": {"subtype": subtype}}
            try:
                assert self.proc.stdin is not None
                self.proc.stdin.write(json.dumps(msg) + "\n")
                self.proc.stdin.flush()
            except OSError as e:
                self._dead = True
                raise SessionDead(f"failed writing to claude stdin: {e}", self.stderr_tail())
            deadline = time.monotonic() + timeout_s
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RequestTimeout(f"no control response after {timeout_s:.0f}s")
                try:
                    ev = self._events.get(timeout=min(remaining, 1.0))
                except queue.Empty:
                    continue
                if ev is None:
                    raise SessionDead("claude process exited mid-request", self.stderr_tail())
                if ev.get("type") != "control_response":
                    continue  # init/rate-limit noise — no turn is in flight under this lock
                resp = ev.get("response", {})
                if resp.get("request_id") != rid:
                    continue
                if resp.get("subtype") == "error":
                    raise SessionError(f"control request {subtype!r} failed: {resp.get('error')}")
                return resp.get("response", {})

    def close(self):
        self._closed = True
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()

    def kill(self):
        """Immediate termination (user cancel) — no graceful wait."""
        self._closed = True
        try:
            self.proc.kill()
        except Exception:
            pass
