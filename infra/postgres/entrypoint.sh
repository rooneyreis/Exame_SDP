#!/usr/bin/env bash
# Entrypoint shared by every PostgreSQL node. Runs as root, then hands over to the
# official docker-entrypoint.sh (which drops to the "postgres" user).
#
# Environment:
#   NODE_NAME     name of this node (selects /certs/<NODE_NAME>.crt/.key)
#   PEER_HOST     (shards only) the other node of the same region
#   INITIAL_ROLE  primary | replica   — role on the very first start (empty data dir)
set -euo pipefail

log() { echo "[pg-entrypoint:$NODE_NAME] $*"; }

# 1. TLS: Postgres refuses a private key readable by others, so copy the bind-mounted
#    files to a private directory owned by "postgres" with mode 0600.
TLS=/var/lib/postgresql/tls
mkdir -p "$TLS"
cp /certs/ca.crt "$TLS/ca.crt"
cp "/certs/$NODE_NAME.crt" "$TLS/server.crt"
cp "/certs/$NODE_NAME.key" "$TLS/server.key"
chown -R postgres:postgres "$TLS"
chmod 600 "$TLS/server.key"

# Asks the peer whether it is in recovery (t = replica, f = primary). Empty if unreachable.
peer_in_recovery() {
  PGPASSWORD="$POSTGRES_PASSWORD" psql -tA \
    "host=$PEER_HOST port=5432 user=postgres dbname=postgres sslmode=verify-full sslrootcert=$TLS/ca.crt connect_timeout=3" \
    -c "SELECT pg_is_in_recovery()" 2>/dev/null || true
}

# Copies the peer's data directory and configures this node as its standby.
clone_from_peer() {
  log "a clonar dados de $PEER_HOST com pg_basebackup (TLS verify-full)..."
  rm -rf "${PGDATA:?}"/*
  chown postgres:postgres "$PGDATA"
  chmod 700 "$PGDATA"
  # -R writes standby.signal + primary_conninfo, -X stream copies WAL during the backup.
  gosu postgres pg_basebackup -R -X stream -D "$PGDATA" \
    -d "host=$PEER_HOST port=5432 user=replicator password=$REPLICATION_PASSWORD sslmode=verify-full sslrootcert=$TLS/ca.crt application_name=$NODE_NAME"
  log "clone concluído: este nó arranca como RÉPLICA (standby) de $PEER_HOST"
}

wait_for_peer_primary() {
  log "à espera que $PEER_HOST esteja disponível como primário..."
  for _ in $(seq 1 90); do
    [[ "$(peer_in_recovery)" == "f" ]] && return 0
    sleep 2
  done
  log "ERRO: $PEER_HOST não ficou disponível como primário"
  exit 1
}

if [[ -n "${PEER_HOST:-}" ]]; then
  if [[ ! -s "$PGDATA/PG_VERSION" ]]; then
    # First start with an empty data directory.
    if [[ "$INITIAL_ROLE" == "replica" ]]; then
      wait_for_peer_primary
      clone_from_peer
    else
      log "primeiro arranque: inicializa como PRIMÁRIO"
    fi
  elif [[ ! -f "$PGDATA/standby.signal" ]]; then
    # This node was a primary. If the peer was promoted meanwhile (failover), coming
    # back as a second primary would cause split-brain: rejoin as its replica instead.
    if [[ "$(peer_in_recovery)" == "f" ]]; then
      log "AVISO: $PEER_HOST já é primário (houve failover). Este nó volta como réplica."
      clone_from_peer
    else
      log "arranca como PRIMÁRIO"
    fi
  else
    log "arranca como RÉPLICA (standby.signal presente)"
  fi
fi

exec docker-entrypoint.sh postgres -c config_file=/etc/postgresql/postgresql.conf
