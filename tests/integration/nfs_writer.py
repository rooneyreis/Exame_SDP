"""Phase 0 NFS check, run inside two containers at the same time.

Each node:
  1. writes its own file /audit/phase0/<node>.log (one file per node: no write conflicts);
  2. increments a SHARED counter /audit/phase0/counter.txt ITERATIONS times.
     read-modify-write is only correct if the exclusive lock (fcntl.lockf, which
     NFS v4 implements on the server) really works across machines;
  3. waits until it can read the other node's file through NFS.

Exit code 0 = success. Output lines are parsed by tests/integration/test_phase0_nfs.py.
"""
import fcntl
import os
import socket
import sys
import time

BASE = "/audit/phase0"
ITERATIONS = 200


def log(node: str, msg: str) -> None:
    print(f"[{node}] {msg}", flush=True)


def increment_shared_counter(node: str, path: str, verbose: bool) -> None:
    # "a+" creates the file if missing without truncating it.
    with open(path, "a+") as f:
        if verbose:
            log(node, "a pedir lock exclusivo (fcntl.lockf) em counter.txt...")
        fcntl.lockf(f, fcntl.LOCK_EX)  # blocks until the other node releases it
        if verbose:
            log(node, "lock adquirido")
        try:
            f.seek(0)
            current = int(f.read().strip() or "0")
            f.seek(0)
            f.truncate()
            f.write(str(current + 1))
            f.flush()
            os.fsync(f.fileno())  # make sure the server has the data before unlocking
        finally:
            fcntl.lockf(f, fcntl.LOCK_UN)
            if verbose:
                log(node, "lock libertado")


def main() -> int:
    node, other = sys.argv[1], sys.argv[2]
    os.makedirs(BASE, exist_ok=True)
    log(node, f"hostname={socket.gethostname()} a escrever em {BASE} (NFS)")

    own_file = f"{BASE}/{node}.log"
    with open(own_file, "w") as f:
        for i in range(10):
            f.write(f"{node} linha {i}\n")
    log(node, f"escrevi 10 linhas em {own_file}")

    counter = f"{BASE}/counter.txt"
    for i in range(ITERATIONS):
        increment_shared_counter(node, counter, verbose=(i < 2))
    log(node, f"incrementei o contador partilhado {ITERATIONS} vezes")

    other_file = f"{BASE}/{other}.log"
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            with open(other_file) as f:
                lines = f.read().splitlines()
            if len(lines) == 10:
                log(node, f"VI_FICHEIRO_DO_OUTRO {other_file}: '{lines[0]}' ... '{lines[-1]}'")
                return 0
        except FileNotFoundError:
            pass
        time.sleep(0.5)
    log(node, f"ERRO: não consegui ler {other_file}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
