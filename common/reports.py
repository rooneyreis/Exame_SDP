"""Daily report shared by several nodes on the NFS: /audit/reports/<YYYY-MM-DD>.json

Unlike the audit logs (one file per node), this ONE file is updated by the coordinator
AND by both api instances, so concurrent access must be controlled:

  1. threading.Lock  -> between threads of the same process. POSIX record locks (fcntl)
                        belong to the PROCESS: two threads of one process would both get
                        the "exclusive" lock and could lose each other's updates.
  2. fcntl.lockf     -> between processes and between nodes. NFS v4 implements it on the
                        server (LOCK operation), so api-1, api-2 and the coordinator, each in
                        its own container, wait for each other.

Each update is a read-modify-write under both locks, followed by fsync before unlocking.
"""
import asyncio
import fcntl
import json
import logging
import os
import threading
import time
from decimal import Decimal
from pathlib import Path

log = logging.getLogger("reports")
_thread_lock = threading.Lock()


def empty_report(day: str) -> dict:
    return {"date": day, "transfers": {"by_state": {}, "by_kind": {}, "volume_by_region": {}},
            "cash": {}, "updates_by_node": {}, "last_update": None}


def _add_money(bucket: dict, currency: str, amount: str) -> None:
    bucket[currency] = f"{Decimal(bucket.get(currency, '0')) + Decimal(amount):.2f}"


def apply_update(report: dict, update: dict, node: str, now: str) -> dict:
    """Pure function: returns the report with one more event counted.

    update = {"type": "transfer", "state", "kind", "region", "currency", "amount"}
           | {"type": "cash", "operation": "DEPOSITO"|"LEVANTAMENTO", "region", "currency", "amount"}
    """
    if update["type"] == "transfer":
        t = report["transfers"]
        t["by_state"][update["state"]] = t["by_state"].get(update["state"], 0) + 1
        t["by_kind"][update["kind"]] = t["by_kind"].get(update["kind"], 0) + 1
        if update["state"] == "CONFIRMADA":   # volume = money that actually left each region
            _add_money(t["volume_by_region"].setdefault(update["region"], {}), update["currency"], update["amount"])
    elif update["type"] == "cash":
        op = report["cash"].setdefault(update["operation"], {}).setdefault(update["region"], {"count": 0, "volume": {}})
        op["count"] += 1
        _add_money(op["volume"], update["currency"], update["amount"])
    report["updates_by_node"][node] = report["updates_by_node"].get(node, 0) + 1
    report["last_update"] = now
    return report


def report_path(base_dir: str, day: str) -> Path:
    return Path(base_dir) / "reports" / f"{day}.json"


def update_daily_report(base_dir: str, node: str, update: dict) -> dict:
    day = time.strftime("%Y-%m-%d", time.gmtime())
    path = report_path(base_dir, day)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _thread_lock:
        with open(path, "a+", encoding="utf-8") as f:      # a+: creates it, never truncates on open
            started = time.perf_counter()
            fcntl.lockf(f, fcntl.LOCK_EX)                  # blocks while another node holds it
            waited = (time.perf_counter() - started) * 1000
            log.info(f"lock NFS adquirido em {path.name} (esperou {waited:.1f} ms)")
            try:
                f.seek(0)
                raw = f.read()
                report = json.loads(raw) if raw.strip() else empty_report(day)
                report = apply_update(report, update, node, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
                f.seek(0)
                f.truncate()
                json.dump(report, f, ensure_ascii=False, indent=2, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())                       # data on the server before unlocking
            finally:
                fcntl.lockf(f, fcntl.LOCK_UN)
                log.info(f"lock NFS libertado em {path.name}")
    return report


async def record(node: str, update: dict, base_dir: str = "/audit") -> None:
    """Async wrapper; a report failure never breaks the business operation."""
    try:
        await asyncio.to_thread(update_daily_report, base_dir, node, update)
    except Exception as exc:
        log.error(f"falha a atualizar o relatório diário: {exc!r}")


def read_report(base_dir: str, day: str) -> dict | None:
    path = report_path(base_dir, day)
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        fcntl.lockf(f, fcntl.LOCK_SH)                      # shared lock: no half-written reads
        try:
            return json.loads(f.read() or "null")
        finally:
            fcntl.lockf(f, fcntl.LOCK_UN)
