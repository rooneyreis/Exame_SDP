"""Tamper-evident audit log on the distributed file system (NFS).

File: /audit/<YYYY-MM-DD>/<node>.log — one file per node, so two nodes never write
to the same file (no write conflicts, no lock needed for the log itself).

Each line is a JSON object with:
  prev_hash  hash of the previous line ("0"*64 for the first line of the day)
  hash       SHA-256(prev_hash + canonical JSON of the line without "hash")
Changing, removing or reordering any line breaks every hash after it: verify_chain()
points to the first broken line.
"""
import asyncio
import json
import logging
import os
import time
from pathlib import Path

from .crypto import canonical_json, sha256_hex

GENESIS = "0" * 64
log = logging.getLogger("audit")


def line_hash(prev_hash: str, entry_without_hash: dict) -> str:
    return sha256_hex(prev_hash.encode() + canonical_json(entry_without_hash))


def verify_chain(lines: list[str]) -> tuple[bool, int | None, str]:
    """Checks a whole file. Returns (ok, first bad line number (1-based) or None, reason)."""
    prev = GENESIS
    for number, raw in enumerate(lines, start=1):
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            return False, number, "linha não é JSON válido"
        claimed = entry.pop("hash", None)
        if entry.get("prev_hash") != prev:
            return False, number, "prev_hash não corresponde à linha anterior"
        if line_hash(prev, entry) != claimed:
            return False, number, "hash não corresponde ao conteúdo (linha alterada)"
        prev = claimed
    return True, None, "cadeia íntegra"


class AuditLog:
    def __init__(self, node: str, base_dir: str = "/audit"):
        self.node = node
        self.base = Path(base_dir)
        self._lock = asyncio.Lock()      # one writer at a time inside this process
        self._day: str | None = None
        self._prev = GENESIS

    def path_for(self, day: str) -> Path:
        return self.base / day / f"{self.node}.log"

    def _load_prev(self, day: str) -> str:
        """Continues the chain after a restart: the last hash of today's file."""
        path = self.path_for(day)
        if not path.exists():
            return GENESIS
        last = None
        with path.open("rb") as f:
            for raw in f:
                if raw.strip():
                    last = raw
        return json.loads(last)["hash"] if last else GENESIS

    def _append(self, event: str, fields: dict) -> None:
        now = time.time()
        day = time.strftime("%Y-%m-%d", time.gmtime(now))
        if day != self._day:
            os.makedirs(self.base / day, exist_ok=True)
            self._prev = self._load_prev(day)
            self._day = day
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now)) + f".{int(now % 1 * 1000):03d}Z",
            "node": self.node, "event": event, **fields, "prev_hash": self._prev,
        }
        entry["hash"] = line_hash(self._prev, entry)
        with self.path_for(day).open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
            f.flush()
            os.fsync(f.fileno())   # on the NFS server before we continue
        self._prev = entry["hash"]

    async def write(self, event: str, **fields) -> None:
        """Never breaks the request: if the NFS is unavailable the failure is logged."""
        async with self._lock:
            try:
                await asyncio.to_thread(self._append, event, fields)
            except Exception as exc:
                self._day = None  # reload the chain on the next write
                log.error(f"falha a escrever auditoria no NFS ({event}): {exc!r}")
