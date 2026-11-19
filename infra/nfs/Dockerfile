# NFS v4 server in user space (NFS-Ganesha), so it does not depend on the
# WSL2/Docker Desktop kernel having nfsd modules.
FROM ubuntu:24.04

RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      nfs-ganesha nfs-ganesha-vfs \
 && rm -rf /var/lib/apt/lists/*

COPY ganesha.conf /etc/ganesha/ganesha.conf
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && mkdir -p /audit /var/run/ganesha /var/lib/nfs/ganesha

EXPOSE 2049
ENTRYPOINT ["/entrypoint.sh"]
