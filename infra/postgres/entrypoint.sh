#!/usr/bin/env bash
# Entrypoint of every PostgreSQL node (pg-core, pg-europa, pg-america, pg-africa).
# Runs as root: prepares TLS files and directories, then hands over to the supervisor
# (as user "postgres"), which runs this node's own database and the copy it keeps of
# another node's database (common/topology.json).
#
# Environment: NODE_NAME (selects /certs/<NODE_NAME>.crt/.key), POSTGRES_PASSWORD,
# REPLICATION_PASSWORD and the service passwords used by the init scripts.
set -euo pipefail

# Postgres refuses a private key readable by others: copy the bind-mounted files to a
# private directory owned by "postgres" with mode 0600.
TLS=/var/lib/postgresql/tls
mkdir -p "$TLS" /var/lib/postgresql/data /var/lib/postgresql/copies /var/run/postgresql
cp /certs/ca.crt "$TLS/ca.crt"
cp "/certs/$NODE_NAME.crt" "$TLS/server.crt"
cp "/certs/$NODE_NAME.key" "$TLS/server.key"
chown -R postgres:postgres /var/lib/postgresql /var/run/postgresql
chmod 600 "$TLS/server.key"
chmod 700 /var/lib/postgresql/data

exec gosu postgres python3 /usr/local/lib/gss/supervisor.py
