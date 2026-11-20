# Instalação num servidor (para a apresentação)

## Requisitos

| | Mínimo | Recomendado |
|---|---|---|
| RAM | 4 GB | **8 GB** |
| CPU | 2 vCPU | 2–4 vCPU |
| Disco | 10 GB livres | 20 GB |
| Sistema | Ubuntu 22.04 / 24.04 | Ubuntu 24.04 |
| Portas abertas no fornecedor | 22, 443 | 22, 80, 443 |

Com 1 GB de RAM **não corre**: são 14 contentores (7 PostgreSQL, uma JVM, 4 serviços Python, NFS e nginx).

## Instalação (um comando)

```bash
ssh utilizador@IP_DO_SERVIDOR
curl -fsSL https://raw.githubusercontent.com/rooneyreis/Exame_SDP/main/scripts/deploy.sh -o deploy.sh
sudo bash deploy.sh
```

O script (`scripts/deploy.sh`) pode ser repetido sem perder dados. Faz por esta ordem:

1. confirma RAM, CPU e disco;
2. instala Docker + Compose, `nfs-common` (necessário para o volume NFS), `git`, `jq`, `make`, `python3-venv`, e configura a rotação dos logs do Docker;
3. clona o repositório (ou faz `git pull`);
4. gera o `.env` com **senhas internas aleatórias**, a CA local e os certificados (o do nginx inclui o IP público) e as chaves RS256/Ed25519/AES;
5. ativa a firewall (`ufw`): SSH, 80 e 443;
6. constrói as imagens e arranca os 14 contentores;
7. cria os dados de demonstração;
8. verifica a interface e a API e mostra o endereço.

No fim: **https://IP_DO_SERVIDOR/**

## Restringir o acesso (recomendado)

As contas de demonstração têm senhas conhecidas (estão no README público). Para que só o docente consiga abrir o site:

```bash
ALLOW_FROM=IP_DO_DOCENTE sudo -E bash deploy.sh          # vários: ALLOW_FROM=ip1,ip2
```

Atenção: o Docker publica as portas por fora do `ufw`. Confirma também, no painel do fornecedor, que a firewall de rede só deixa passar 22, 80 e 443 (e, se possível, 443 só a partir do IP do docente).

O mais simples e seguro: **arrancar só para a apresentação** e parar a seguir.

```bash
cd ~/global-scale-system
docker compose up -d --wait      # antes da apresentação
docker compose down              # depois (os dados ficam guardados nos volumes)
```

## Aviso de certificado no browser

Sem domínio, o certificado é emitido pela CA local do projeto, por isso o browser avisa. Duas opções no computador da apresentação:

- clicar em **Avançado → Continuar** (só para essa sessão);
- ou importar a CA (o cadeado fica normal):
  ```powershell
  scp utilizador@IP_DO_SERVIDOR:~/global-scale-system/infra/certs/ca.crt $env:TEMP\gs-ca.crt
  Import-Certificate -FilePath $env:TEMP\gs-ca.crt -CertStoreLocation Cert:\CurrentUser\Root
  ```

## Demonstração no servidor

```bash
cd ~/global-scale-system
make test                          # suite completa (~5 min)
PAUSE=1 ./scripts/demo/run-all.sh  # os 14 cenários com pausas
```

## Problemas comuns

| Sintoma | Causa / solução |
|---|---|
| `permission denied ... docker.sock` | O utilizador foi adicionado ao grupo `docker`: sair e voltar a entrar por SSH. |
| Contentores com `unhealthy` logo após arrancar | Primeira inicialização das BDs: esperar 1 minuto e `docker compose up -d --wait`. |
| `mount.nfs: ... failed` ao arrancar | Falta `nfs-common` (o script instala-o): `sudo apt install nfs-common`. |
| Site não abre de fora | Firewall do fornecedor a bloquear 443, ou `ALLOW_FROM` com outro IP. |
| Pouca memória (`docker stats`) | Confirmar que a máquina tem 8 GB; parar outros serviços. |
