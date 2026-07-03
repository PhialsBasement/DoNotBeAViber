"""Learning log: workspace-local JSONL at .nlv/log.jsonl (spec section 10).

Local-first, append-only, gitignored by default. One record per event.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone


class JsonlLogger:
    def __init__(self, workspace: str):
        self.dir = os.path.join(workspace, ".nlv")
        self.path = os.path.join(self.dir, "log.jsonl")
        self._lock = threading.Lock()

    def log(self, event: str, **fields) -> None:
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "event": event,
            **{k: v for k, v in fields.items() if v is not None},
        }
        with self._lock:
            os.makedirs(self.dir, exist_ok=True)
            gitignore = os.path.join(self.dir, ".gitignore")
            if not os.path.exists(gitignore):
                with open(gitignore, "w", encoding="utf-8") as f:
                    f.write("*\n")
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
