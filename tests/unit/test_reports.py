"""Daily report aggregation (common/reports.py)."""
import json
import threading

from common.reports import apply_update, empty_report, update_daily_report


def test_transfer_counts_and_volume():
    r = empty_report("2026-11-20")
    r = apply_update(r, {"type": "transfer", "state": "CONFIRMADA", "kind": "DISTRIBUIDA", "region": "EU",
                         "currency": "EUR", "amount": "100.00"}, "coordinator", "t1")
    r = apply_update(r, {"type": "transfer", "state": "CONFIRMADA", "kind": "LOCAL", "region": "EU",
                         "currency": "EUR", "amount": "0.50"}, "coordinator", "t2")
    r = apply_update(r, {"type": "transfer", "state": "ABORTADA", "kind": "DISTRIBUIDA", "region": "AM",
                         "currency": "USD", "amount": "9.00"}, "coordinator", "t3")
    assert r["transfers"]["by_state"] == {"CONFIRMADA": 2, "ABORTADA": 1}
    assert r["transfers"]["by_kind"] == {"DISTRIBUIDA": 2, "LOCAL": 1}
    assert r["transfers"]["volume_by_region"] == {"EU": {"EUR": "100.50"}}   # aborted ones move no money
    assert r["updates_by_node"] == {"coordinator": 3} and r["last_update"] == "t3"


def test_cash_operations_per_region():
    r = empty_report("d")
    for node in ("api-1", "api-2"):
        r = apply_update(r, {"type": "cash", "operation": "DEPOSITO", "region": "AM", "currency": "USD",
                             "amount": "10.10"}, node, "t")
    assert r["cash"]["DEPOSITO"]["AM"] == {"count": 2, "volume": {"USD": "20.20"}}
    assert r["updates_by_node"] == {"api-1": 1, "api-2": 1}


def test_concurrent_threads_lose_no_update(tmp_path):
    """fcntl locks are per process: the threading.Lock is what protects threads here."""
    update = {"type": "cash", "operation": "DEPOSITO", "region": "EU", "currency": "EUR", "amount": "1.00"}
    threads = [threading.Thread(target=lambda: [update_daily_report(str(tmp_path), "api-1", update) for _ in range(10)])
               for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    report = json.loads(next((tmp_path / "reports").glob("*.json")).read_text())
    assert report["cash"]["DEPOSITO"]["EU"] == {"count": 80, "volume": {"EUR": "80.00"}}
