"""Hash-chained audit log (common/audit.py)."""
import json

from common.audit import GENESIS, AuditLog, verify_chain
from common.crypto import canonical_json


def write_lines(tmp_path, n=5):
    log = AuditLog("api-1", str(tmp_path))
    for i in range(n):
        log._append("DEPOSITO", {"iban": "GS-EU-00000001", "amount": f"{i}.00"})
    path = log.path_for(log._day)
    return log, path


def test_chain_of_untouched_file_is_valid(tmp_path):
    _, path = write_lines(tmp_path)
    assert verify_chain(path.read_text().splitlines()) == (True, None, "cadeia íntegra")


def test_first_line_links_to_genesis_and_each_line_to_the_previous(tmp_path):
    _, path = write_lines(tmp_path, 3)
    entries = [json.loads(l) for l in path.read_text().splitlines()]
    assert entries[0]["prev_hash"] == GENESIS
    assert entries[1]["prev_hash"] == entries[0]["hash"]
    assert entries[2]["prev_hash"] == entries[1]["hash"]


def test_modified_line_is_detected(tmp_path):
    _, path = write_lines(tmp_path)
    lines = path.read_text().splitlines()
    entry = json.loads(lines[2])
    entry["amount"] = "999999.00"                  # attacker changes the amount, keeps the hash
    lines[2] = json.dumps(entry)
    ok, line, reason = verify_chain(lines)
    assert (ok, line) == (False, 3) and "alterada" in reason


def test_recomputed_hash_still_breaks_the_next_line(tmp_path):
    from common.audit import line_hash
    _, path = write_lines(tmp_path)
    lines = path.read_text().splitlines()
    entry = json.loads(lines[1])
    entry.pop("hash")
    entry["amount"] = "999999.00"
    entry["hash"] = line_hash(entry["prev_hash"], entry)   # attacker also fixes this line's hash
    lines[1] = json.dumps(entry)
    ok, line, reason = verify_chain(lines)
    assert (ok, line) == (False, 3) and "prev_hash" in reason


def test_deleted_line_is_detected(tmp_path):
    _, path = write_lines(tmp_path)
    lines = path.read_text().splitlines()
    del lines[1]
    assert verify_chain(lines)[:2] == (False, 2)


def test_chain_continues_after_restart(tmp_path):
    log, path = write_lines(tmp_path, 2)
    again = AuditLog("api-1", str(tmp_path))           # new process, same file
    again._append("LEVANTAMENTO", {"iban": "GS-EU-00000001"})
    assert verify_chain(path.read_text().splitlines())[0]


def test_canonical_json_is_deterministic():
    assert canonical_json({"b": 1, "a": "é"}) == canonical_json({"a": "é", "b": 1}) == '{"a":"é","b":1}'.encode()
