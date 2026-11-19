#!/usr/bin/env bash
set -euo pipefail

mkdir -p /audit/reports
chmod 777 /audit /audit/reports

echo "[nfs] A arrancar NFS-Ganesha (NFS v4) a exportar /audit..."
# -F: foreground, -L: log to stdout, -N: log level
exec ganesha.nfsd -F -L /dev/stdout -N NIV_EVENT -f /etc/ganesha/ganesha.conf
