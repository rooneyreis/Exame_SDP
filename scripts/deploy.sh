#!/usr/bin/env bash
# Instala e arranca o Global-Scale System num servidor Ubuntu (22.04/24.04) acabado de criar.
#
#   curl -fsSL https://raw.githubusercontent.com/rooneyreis/Exame_SDP/main/scripts/deploy.sh -o deploy.sh
#   sudo bash deploy.sh                      # deteta o IP público
#   sudo bash deploy.sh 203.0.113.10         # ou indica-o
#   ALLOW_FROM=198.51.100.7 sudo -E bash deploy.sh   # só esse IP (ex.: o do docente) acede ao site
#
# Pode ser repetido: não apaga dados nem volta a gerar segredos que já existam.
set -euo pipefail

REPO_URL=${REPO_URL:-https://github.com/rooneyreis/Exame_SDP.git}
APP_USER=${SUDO_USER:-$(whoami)}
APP_HOME=$(getent passwd "$APP_USER" | cut -d: -f6)
APP_DIR=${APP_DIR:-$APP_HOME/global-scale-system}
PUBLIC_IP=${1:-}

say()  { printf '\n\033[1;36m▶ %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m  ✔ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m  ! %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m  ✘ %s\033[0m\n' "$*"; exit 1; }

[[ $EUID -eq 0 ]] || die "Corre com sudo: sudo bash $0"
. /etc/os-release
[[ "$ID" == "ubuntu" ]] || warn "Testado em Ubuntu; este sistema é $PRETTY_NAME"

# ------------------------------------------------------------------ requisitos
say "1/8 Requisitos da máquina"
mem_gb=$(awk '/MemTotal/ {printf "%.1f", $2/1024/1024}' /proc/meminfo)
cpus=$(nproc)
disk_gb=$(df -BG --output=avail / | tail -1 | tr -dc 0-9)
echo "  CPU: $cpus · RAM: ${mem_gb} GB · disco livre: ${disk_gb} GB"
awk "BEGIN{exit !($mem_gb < 3.5)}" && die "São precisos pelo menos 4 GB de RAM (recomendado 8 GB): 14 contentores, incluindo 7 PostgreSQL e uma JVM."
awk "BEGIN{exit !($mem_gb < 7)}" && warn "Com menos de 8 GB funciona, mas os cenários de falha e concorrência podem ficar lentos."
(( disk_gb >= 10 )) || die "São precisos pelo menos 10 GB livres em disco (imagens Docker + bases de dados)."
ok "máquina adequada"

# ------------------------------------------------------------------ pacotes
say "2/8 Pacotes do sistema"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
# nfs-common: o volume NFS da auditoria é montado pelo próprio Docker do servidor (mount.nfs).
apt-get install -y -qq ca-certificates curl git make jq openssl python3 python3-venv nfs-common ufw >/dev/null
if ! command -v docker >/dev/null || ! docker compose version >/dev/null 2>&1; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -qq
  apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin >/dev/null
fi
usermod -aG docker "$APP_USER"
ok "$(docker --version), $(docker compose version | head -1)"

# Logs dos contentores com rotação (não enchem o disco)
if [[ ! -f /etc/docker/daemon.json ]]; then
  cat > /etc/docker/daemon.json <<'JSON'
{ "log-driver": "json-file", "log-opts": { "max-size": "10m", "max-file": "3" } }
JSON
  systemctl restart docker
fi
ok "rotação de logs do Docker ativa (10 MB × 3 por contentor)"

# ------------------------------------------------------------------ código
say "3/8 Código"
if [[ -d "$APP_DIR/.git" ]]; then
  sudo -u "$APP_USER" git -C "$APP_DIR" pull --ff-only
else
  sudo -u "$APP_USER" git clone "$REPO_URL" "$APP_DIR"
fi
cd "$APP_DIR"
ok "$(git log --oneline -1)"

# ------------------------------------------------------------------ IP público
if [[ -z "$PUBLIC_IP" ]]; then
  PUBLIC_IP=$(curl -fsS --max-time 5 https://api.ipify.org || hostname -I | awk '{print $1}')
fi
[[ "$PUBLIC_IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "Não consegui determinar o IP público. Corre: sudo bash $0 <IP>"
ok "IP público: $PUBLIC_IP"

# ------------------------------------------------------------------ segredos
say "4/8 Segredos (.env, certificados TLS, chaves)"
if [[ ! -f .env ]]; then
  rnd() { openssl rand -hex 16; }
  cat > .env <<EOF
COMPOSE_PROJECT_NAME=gss
# Gerado por deploy.sh em $(date -u +%FT%TZ). Senhas internas (nunca saem do servidor).
POSTGRES_PASSWORD=$(rnd)
REPLICATION_PASSWORD=$(rnd)
AUTH_DB_PASSWORD=$(rnd)
COORD_DB_PASSWORD=$(rnd)
API_DB_PASSWORD=$(rnd)
MAX_SETTLEMENT=20000
EOF
  chown "$APP_USER": .env
  chmod 600 .env
  ok ".env criado com senhas aleatórias"
else
  ok ".env já existe (mantido)"
fi
if [[ ! -f infra/certs/ca.key ]]; then
  sudo -u "$APP_USER" env NGINX_EXTRA_SANS="IP:$PUBLIC_IP" ./scripts/gen-certs.sh >/dev/null
  ok "CA local e certificados gerados (nginx válido também para $PUBLIC_IP)"
else
  ok "certificados já existem (mantidos)"
fi
sudo -u "$APP_USER" ./scripts/gen-keys.sh >/dev/null
ok "chaves RS256 / Ed25519 / AES prontas"

# Só no servidor: publicar também a porta 80 (apenas redireciona para HTTPS)
cat > docker-compose.override.yml <<'YAML'
# Gerado por scripts/deploy.sh (não versionado): no servidor a porta 80 só redireciona para HTTPS.
services:
  nginx:
    ports:
      - "80:80"
YAML
chown "$APP_USER": docker-compose.override.yml

# ------------------------------------------------------------------ firewall
say "5/8 Firewall"
ufw allow OpenSSH >/dev/null
if [[ -n "${ALLOW_FROM:-}" ]]; then
  ufw delete allow 443/tcp >/dev/null 2>&1 || true
  ufw delete allow 80/tcp >/dev/null 2>&1 || true
  for ip in ${ALLOW_FROM//,/ }; do
    ufw allow from "$ip" to any port 443 proto tcp >/dev/null
    ufw allow from "$ip" to any port 80 proto tcp >/dev/null
  done
  ok "site acessível apenas a partir de: $ALLOW_FROM"
else
  ufw allow 443/tcp >/dev/null
  ufw allow 80/tcp >/dev/null
  warn "site acessível a partir de qualquer IP (usa ALLOW_FROM=<ip> para restringir)"
fi
ufw --force enable >/dev/null
warn "Docker publica portas por fora do ufw: confirma também a firewall do fornecedor (só 22, 80, 443)."

# ------------------------------------------------------------------ arranque
say "6/8 Construir e arrancar (a primeira vez demora alguns minutos)"
sudo -u "$APP_USER" -g docker docker compose up -d --build --wait
ok "$(docker compose ps --status running -q | wc -l) contentores a correr"

say "7/8 Dados de demonstração"
sudo -u "$APP_USER" -g docker ./scripts/seed.sh | grep -E '^\[seed\] (Concluído|senhas)' || true

say "8/8 Verificação"
code=$(curl -s -o /dev/null -w '%{http_code}' --cacert infra/certs/ca.crt "https://$PUBLIC_IP/app/" --resolve "$PUBLIC_IP:443:127.0.0.1" || true)
[[ "$code" == 200 ]] && ok "interface web a responder" || warn "a interface respondeu HTTP $code"
health=$(curl -s --cacert infra/certs/ca.crt https://localhost/health | jq -r .status 2>/dev/null || true)
[[ "$health" == ok ]] && ok "API a responder" || warn "a API ainda não respondeu (espera um minuto e repete: curl -k https://localhost/health)"

cat <<EOF

══════════════════════════════════════════════════════════════════
  Global-Scale System instalado
  Interface:  https://$PUBLIC_IP/
  API docs:   https://$PUBLIC_IP/docs

  O certificado é da CA local do projeto: o browser mostra um aviso.
  Para não aparecer, importar no computador da apresentação:
    $APP_DIR/infra/certs/ca.crt   (copiar com: scp $APP_USER@$PUBLIC_IP:$APP_DIR/infra/certs/ca.crt .)

  Utilizadores de demonstração: ver README (senhas Staff#2026 / Cliente#2026).
  Depois da apresentação:  cd $APP_DIR && docker compose down     (para tudo)
══════════════════════════════════════════════════════════════════
EOF
