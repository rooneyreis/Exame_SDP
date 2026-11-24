# PostgreSQL node: the official image + the supervisor that runs this node's database and
# the copy of another node's database, with automatic takeover (infra/postgres/supervisor.py).
# Build context: repository root (needs common/topology.json).
FROM postgres:16

RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 \
 && rm -rf /var/lib/apt/lists/*

COPY common/topology.json /etc/gss/topology.json
COPY infra/postgres/failover_rules.py infra/postgres/supervisor.py /usr/local/lib/gss/
COPY infra/postgres/entrypoint.sh /usr/local/bin/gss-entrypoint.sh
RUN chmod 755 /usr/local/bin/gss-entrypoint.sh

ENTRYPOINT ["/usr/local/bin/gss-entrypoint.sh"]
