#!/usr/bin/env python3
"""Supervisor of the PostgreSQL clusters of ONE node (PID 1 of the container, user postgres).

Every node of the ring runs its own database (HOME, port 5432) and the copy of another
node's database (COPY, port 5433; pg-america also keeps the copy of pg-core on 5434), as
described in common/topology.json. Every 2 seconds, for each cluster, it looks at the
local cluster, at the other location of the same cluster (peer) and at the other nodes
(witnesses), and applies the decision of failover_rules.decide():

  - the copy is a streaming standby of the home (synchronous replication: a commit is only
    confirmed once it is on both nodes, so taking over never loses confirmed transactions);
  - the home fails  -> after FAILOVER_AFTER seconds the copy is promoted and takes its role
                       (clients follow by themselves: multi-host conninfo, read-write);
  - the home is back -> it re-syncs from the copy (base backup), then the copy hands the role
                       back (switchover) and becomes the copy again.

Only the standard library and the PostgreSQL client tools (psql, pg_basebackup, pg_ctl).
"""
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import failover_rules as R  # noqa: E402

TOPOLOGY = json.loads(Path(os.environ.get("TOPOLOGY_FILE", "/etc/gss/topology.json")).read_text())
NODE = os.environ["NODE_NAME"]
PASSWORD = os.environ["POSTGRES_PASSWORD"]
REPL_PASSWORD = os.environ["REPLICATION_PASSWORD"]
TLS = "/var/lib/postgresql/tls"
CONF = "/etc/postgresql/postgresql.conf"
SOCKET = "/var/run/postgresql"
INIT_DIR = Path("/docker-entrypoint-initdb.d")
TICK = 2
FAILOVER_AFTER = float(TOPOLOGY.get("failover_after_seconds", 6))
LOSS_WINDOW = 15      # the copy must have been streaming at most this long before the home vanished


def log(cluster: str | None, msg: str) -> None:
    print(f"[supervisor {NODE}{'/' + cluster if cluster else ''}] {msg}", flush=True)


def psql(conninfo: str, *statements: str, timeout: float = 8) -> str | None:
    """Runs each statement in its own -c (ALTER SYSTEM cannot run inside a transaction
    block). Returns the output, or None if the server could not be reached / failed."""
    cmd = ["psql", "-XtAq", "-v", "ON_ERROR_STOP=1", "-F", "|", conninfo]
    for s in statements:
        cmd += ["-c", s]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           env={**os.environ, "PGPASSWORD": PASSWORD, "PGCONNECT_TIMEOUT": "3"})
    except subprocess.TimeoutExpired:
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def remote(host: str, port: int) -> str:
    return (f"host={host}.global.local port={port} user=postgres dbname=postgres sslmode=verify-full "
            f"sslrootcert={TLS}/ca.crt connect_timeout=3 application_name=gss-supervisor")


def reachable(node: str) -> bool:
    try:
        with socket.create_connection((f"{node}.global.local", 5432), timeout=2):
            return True
    except OSError:
        return False


def status_sql(peer_app: str) -> str:
    return f"""
    SELECT x.r, y.* FROM (SELECT pg_is_in_recovery() AS r) x, LATERAL (SELECT
      CASE WHEN x.r THEN 0 ELSE ('x' || substr(pg_walfile_name(pg_current_wal_lsn()), 1, 8))::bit(32)::int END,
      current_setting('default_transaction_read_only'),
      current_setting('synchronous_standby_names') <> '',
      COALESCE((SELECT status FROM pg_stat_wal_receiver), ''),
      CASE WHEN x.r THEN false ELSE EXISTS (SELECT 1 FROM pg_stat_replication
           WHERE application_name = '{peer_app}' AND state = 'streaming') END,
      CASE WHEN x.r THEN false ELSE EXISTS (SELECT 1 FROM pg_stat_replication
           WHERE application_name = '{peer_app}' AND state = 'streaming'
             AND pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn) < 1048576) END) y"""


def parse_status(out: str | None) -> R.Status | None:
    if not out:
        return None
    f = out.splitlines()[0].split("|")
    return R.Status(primary=f[0] == "f", timeline=int(f[1]), read_only=f[2] == "on", sync=f[3] == "t",
                    streaming=f[4] == "streaming", peer_streaming=f[5] == "t", peer_caught_up=f[6] == "t")


class Cluster:
    def __init__(self, name: str, spec: dict):
        self.name = name
        home, copy = spec["home"], spec["copy"]
        self.role = "home" if home[0] == NODE else "copy"
        self.port = home[1] if self.role == "home" else copy[1]
        self.peer_host, self.peer_port = (copy if self.role == "home" else home)
        self.init_kind = spec.get("init")
        self.dir = Path("/var/lib/postgresql/data") if self.role == "home" \
            else Path(f"/var/lib/postgresql/copies/{name}")
        self.app = f"{self.role}_{name}"                                  # our name when streaming
        self.peer_app = f"{'copy' if self.role == 'home' else 'home'}_{name}"
        self.witnesses = [n for n in TOPOLOGY["nodes"] if n not in (NODE, self.peer_host)]
        self.local_conn = f"host={SOCKET} port={self.port} user=postgres dbname=postgres"
        self.proc: subprocess.Popen | None = None
        self.peer_missing_since: float | None = None
        self.last_streaming_at: float | None = None
        self.not_streaming_since: float | None = None

    # ---- state ----
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def local_status(self) -> R.Status | None:
        return parse_status(psql(self.local_conn, status_sql(self.peer_app)))

    def peer_status(self) -> R.Status | None:
        return parse_status(psql(remote(self.peer_host, self.peer_port), status_sql(self.app)))

    def has_data(self) -> bool:
        return (self.dir / "PG_VERSION").exists()

    # ---- processes ----
    def start(self) -> None:
        log(self.name, f"a arrancar ({self.role}, porta {self.port}, "
                       f"{'standby' if (self.dir / 'standby.signal').exists() else 'primário'})")
        self.proc = subprocess.Popen(["postgres", "-D", str(self.dir), "-p", str(self.port),
                                      "-c", f"config_file={CONF}", "-c", f"cluster_name={self.name}-{self.role}"])
        for _ in range(90):
            if subprocess.run(["pg_isready", "-q", "-h", SOCKET, "-p", str(self.port)]).returncode == 0:
                return
            if self.proc.poll() is not None:
                log(self.name, "ERRO: o postgres terminou ao arrancar")
                return
            time.sleep(1)

    def stop(self) -> None:
        if not self.running():
            return
        log(self.name, "a parar")
        subprocess.run(["pg_ctl", "stop", "-D", str(self.dir), "-m", "fast", "-w", "-t", "60"],
                       capture_output=True)
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.proc = None

    # ---- actions ----
    def init_primary(self) -> None:
        log(self.name, "primeiro arranque: base nova (initdb + scripts de inicialização)")
        self.dir.mkdir(parents=True, exist_ok=True)
        self.dir.chmod(0o700)
        pwfile = Path("/tmp/.pgpw")
        pwfile.write_text(PASSWORD)
        subprocess.run(["initdb", "-D", str(self.dir), "-U", "postgres", f"--pwfile={pwfile}",
                        "--auth-local=trust", "--auth-host=scram-sha-256"], check=True, capture_output=True)
        pwfile.unlink()
        self.start()
        env = {**os.environ, "PGHOST": SOCKET, "PGPORT": str(self.port), "SHARD_REGION": self.name}
        for script in sorted(INIT_DIR.glob("*.sh")):
            log(self.name, f"a correr {script.name}")
            subprocess.run(["bash", str(script)], env=env, check=True)
        self.ensure_replicator()

    def ensure_replicator(self) -> None:
        pw = REPL_PASSWORD.replace("'", "''")
        psql(self.local_conn, "DO $$BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'replicator') "
                              f"THEN CREATE ROLE replicator WITH REPLICATION LOGIN PASSWORD '{pw}'; END IF; END$$")

    def make_standby(self) -> None:
        """Configures the data directory to follow the peer (standby.signal + primary_conninfo)."""
        (self.dir / "standby.signal").touch()
        auto = self.dir / "postgresql.auto.conf"
        keep = [line for line in (auto.read_text().splitlines() if auto.exists() else [])
                if not line.startswith(("primary_conninfo", "synchronous_standby_names",
                                        "default_transaction_read_only"))]
        keep.append(f"primary_conninfo = 'host={self.peer_host}.global.local port={self.peer_port} user=replicator "
                    f"password={REPL_PASSWORD} sslmode=verify-full sslrootcert={TLS}/ca.crt "
                    f"application_name={self.app}'")
        auto.write_text("\n".join(keep) + "\n")

    def clone(self) -> None:
        """Fresh copy of the peer (base backup over TLS), then runs as its standby."""
        self.stop()
        log(self.name, f"a copiar a base de {self.peer_host}:{self.peer_port} (pg_basebackup)")
        if self.dir.exists():
            for child in self.dir.iterdir():
                shutil.rmtree(child) if child.is_dir() else child.unlink()
        self.dir.mkdir(parents=True, exist_ok=True)
        self.dir.chmod(0o700)
        r = subprocess.run(["pg_basebackup", "-X", "stream", "-D", str(self.dir), "-d",
                            f"host={self.peer_host}.global.local port={self.peer_port} user=replicator "
                            f"password={REPL_PASSWORD} sslmode=verify-full sslrootcert={TLS}/ca.crt "
                            f"application_name={self.app}"], capture_output=True, text=True)
        if r.returncode:
            log(self.name, f"pg_basebackup falhou: {r.stderr.strip()[-300:]}")
            return
        self.make_standby()
        self.start()

    def promote(self) -> None:
        log(self.name, f"PROMOÇÃO: {self.peer_host} não está disponível como primário; "
                       f"{NODE} assume o papel de {self.name}")
        psql(self.local_conn, "SELECT pg_promote(true, 60)", timeout=70)
        psql(self.local_conn, "ALTER SYSTEM RESET default_transaction_read_only",
             "ALTER SYSTEM SET synchronous_standby_names = ''", "SELECT pg_reload_conf()")
        self.ensure_replicator()
        self.peer_missing_since = None

    def fence(self) -> None:
        log(self.name, "ISOLADO (não vê a cópia nem outro nó): fica só de leitura")
        psql(self.local_conn, "ALTER SYSTEM SET default_transaction_read_only = on", "SELECT pg_reload_conf()",
             "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
             "WHERE backend_type = 'client backend' AND pid <> pg_backend_pid()")

    def unfence(self) -> None:
        log(self.name, "volta a aceitar escritas")
        psql(self.local_conn, "ALTER SYSTEM RESET default_transaction_read_only", "SELECT pg_reload_conf()")

    def set_sync(self, on: bool) -> None:
        log(self.name, f"replicação {'SÍNCRONA com ' + self.peer_app if on else 'assíncrona (a cópia está em baixo)'}")
        names = f"'\"{self.peer_app}\"'" if on else "''"
        psql(self.local_conn, f"ALTER SYSTEM SET synchronous_standby_names = {names}", "SELECT pg_reload_conf()")

    def switchover(self) -> None:
        """The home is back and in step: stop accepting writes, let it receive the last WAL,
        stop (the shutdown checkpoint is streamed to it) and come back as its standby. The
        home sees both locations as standby and promotes itself."""
        log(self.name, f"RETOMA: {self.peer_host} voltou e está sincronizado; devolve-lhe o papel de {self.name}")
        self.fence()
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            lag = psql(self.local_conn, "SELECT pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn) "
                                        f"FROM pg_stat_replication WHERE application_name = '{self.peer_app}'")
            if lag is not None and lag.strip() in ("0", "0.0"):
                break
            time.sleep(0.5)
        self.stop()
        self.make_standby()
        self.start()

    # ---- one tick ----
    def tick(self) -> None:
        running = self.running()
        local = self.local_status() if running else None
        if running and local is None:
            return                      # starting up or busy: look again next tick
        peer = self.peer_status()
        now = time.monotonic()
        if peer is not None and peer.primary:
            self.peer_missing_since = None
        elif self.peer_missing_since is None:
            self.peer_missing_since = now
        if local is not None and not local.primary:
            if local.streaming:
                self.last_streaming_at, self.not_streaming_since = now, None
            elif self.not_streaming_since is None:
                self.not_streaming_since = now
        streamed = (self.last_streaming_at is not None and self.peer_missing_since is not None
                    and self.peer_missing_since - self.last_streaming_at <= LOSS_WINDOW)
        witness_ok = any(reachable(n) for n in self.witnesses)

        action = R.decide(
            role=self.role, has_data=self.has_data(), standby_signal=(self.dir / "standby.signal").exists(),
            local=local, peer=peer, witness_ok=witness_ok,
            peer_missing_for=(now - self.peer_missing_since) if self.peer_missing_since else 0,
            streamed_before_loss=streamed, failover_after=FAILOVER_AFTER,
            not_streaming_for=(now - self.not_streaming_since) if self.not_streaming_since else 0)

        if action == R.INIT_PRIMARY:
            self.init_primary()
        elif action in (R.CLONE, R.STEP_DOWN):
            if action == R.STEP_DOWN:
                log(self.name, f"{self.peer_host} é o primário mais recente: esta base passa a cópia dele")
            self.clone()
            self.not_streaming_since = None
        elif action == R.START:
            self.start()
        elif action == R.PROMOTE:
            self.promote()
        elif action == R.SWITCHOVER:
            self.switchover()
        elif action == R.FENCE:
            self.fence()
        elif action == R.UNFENCE:
            self.unfence()
        elif action in (R.SYNC_ON, R.SYNC_OFF):
            self.set_sync(action == R.SYNC_ON)
        if local is not None and local.primary and action in (R.OK, R.SYNC_ON, R.SYNC_OFF):
            self.ensure_replicator_once()

    _replicator_checked = False

    def ensure_replicator_once(self) -> None:
        if not self._replicator_checked:
            self.ensure_replicator()
            self._replicator_checked = True


def main() -> None:
    specs = TOPOLOGY["clusters"]
    clusters = [Cluster(n, s) for n, s in specs.items() if NODE in (s["home"][0], s["copy"][0])]
    clusters.sort(key=lambda c: c.role != "home")           # own database first
    log(None, "bases neste nó: " + ", ".join(f"{c.name} ({'dono' if c.role == 'home' else 'cópia'}, "
                                             f"porta {c.port})" for c in clusters))
    stopping = False

    def on_signal(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    while not stopping:
        started = time.monotonic()
        for c in clusters:
            if stopping:
                break
            try:
                c.tick()
            except Exception as exc:          # never let one cluster stop the others
                log(c.name, f"erro: {exc!r}")
        while not stopping and time.monotonic() - started < TICK:
            time.sleep(0.2)
    for c in clusters:
        c.stop()
    log(None, "terminado")


if __name__ == "__main__":
    main()
