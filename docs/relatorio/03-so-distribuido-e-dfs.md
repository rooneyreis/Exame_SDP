# Sistema Operativo Distribuído e DFS (rascunho — notas recolhidas na Fase 0)

> Notas para desenvolver no relatório. Completar na Fase 6 (relatórios diários com lock).

## Implementação

- Servidor: NFS-Ganesha, NFS v4, export `/audit` (`infra/nfs/ganesha.conf`).
- Clientes: volume Docker `audit` com `type: nfs`, `device: ":/audit"`, `addr=172.28.0.50` (`docker-compose.yml`).
- Evidência de mount (`/proc/mounts` dentro de um cliente):
  `:/audit /audit nfs4 rw,vers=4.0,hard,proto=tcp,timeo=50,local_lock=none,addr=172.28.0.50`

## Transparência de localização

- O mesmo caminho `/audit/...` em todos os nós. A aplicação usa `open()`/`write()` normais, sem saber que o disco está no nó `nfs` (172.28.0.50).
- Quem traduz as chamadas ao sistema em pedidos de rede é a camada VFS do kernel Linux: VFS → cliente NFS → RPC sobre TCP 2049 → Ganesha → disco.
- Transparência de acesso: a mesma API POSIX para ficheiros locais e remotos.
- Ligação à teoria: é o modelo de *mount* remoto, com um espaço de nomes único (*pseudo filesystem* do NFSv4, `Pseudo = /audit`).

## Acesso concorrente

- NFS v4 é um protocolo **com estado** para locks: o servidor guarda quem tem cada lock (*lock owner*) e o *lease*. Se o cliente não renovar dentro de `Lease_Lifetime` (15 s), o servidor liberta os locks dele (evita locks presos se um nó morrer).
- `fcntl.lockf(LOCK_EX)` no cliente → operação `LOCK` do NFSv4 → o servidor arbitra (`local_lock=none` confirma que não é resolvido localmente).
- Estratégia da aplicação: cada nó escreve no **seu** ficheiro (`/audit/<data>/<serviço>.log`), o que evita conflitos. Os ficheiros partilhados (relatório diário) usam lock exclusivo.
- Evidência: `tests/integration/nfs_writer.py`. Dois nós fazem 200 read-modify-write cada no mesmo contador e o valor final é 400. Sem lock haveria atualizações perdidas (condição de corrida).
- Consistência de cache: semântica *close-to-open* (ao abrir, o cliente revalida os atributos; ao fechar, envia os dados). Por isso o escritor faz `fsync` antes de libertar o lock.

## Docker/Linux como "SO distribuído"

- Namespaces de rede: cada contentor tem a sua pilha TCP/IP, o seu IP fixo e DNS (`*.global.local`) resolvido pelo DNS interno do Docker.
- Volumes: o daemon monta o NFS e entrega-o ao contentor (transparência de localização também para o *deploy*).
- Honestidade técnica: em Docker Desktop todos os contentores correm na mesma VM, por isso é uma **simulação** de nós separados (todos os mounts têm `clientaddr=172.28.0.1`).

## Lição prática: coerência de cache (Fase 2)

- Um teste apagava `/audit/phase0` **diretamente no servidor**, por fora do NFS. Com outro contentor (`auth`) a manter o volume montado, o cliente NFS (partilhado na VM do Docker) manteve a entrada do diretório em cache. A execução seguinte recebia `ENOENT` ao criar ficheiros lá dentro.
- Explicação: o cliente NFS guarda atributos e entradas de diretório em cache durante alguns segundos (`acdirmin`/`acdirmax`). A coerência só é garantida para operações que passam pelo protocolo (close-to-open).
- Correção: a limpeza passa a ser feita por um cliente NFS. Mostra porque é que, num DFS, toda a escrita tem de passar pela camada distribuída.
