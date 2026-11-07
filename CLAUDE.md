> **Atenção (ARES 2.0):** as seções abaixo descrevem a infraestrutura do ARES 1 (produção). O predator2 roda em LXC nova e usa o banco do 2.0; nunca aponte para o banco ou a LXC 105 de produção.

# ARES - BI Acerta Express

## Contexto do Projeto
Sistema de BI para a transportadora **Acerta Express**, extraindo dados do TMS **Brudam** a cada 30 minutos, armazenando em PostgreSQL e exibindo no Grafana.

## Infraestrutura

### VPS (Contabo Europa - geo-bloqueada pelo Brudam)
- IP: `173.249.15.221`
- SSH: `root` (senha fora do git)
- Dokploy: `http://173.249.15.221:3000`
- Dokploy API token: (fora do git — variável DOKPLOY_TOKEN no .env)
- Dokploy API auth header: `x-api-key`

### PostgreSQL (ARES - porta externa)
- Host: `173.249.15.221`
- Porta: `5433`
- Banco: `ares_bi`
- Usuário: `ares`
- Senha: `(ver .env — fora do git)`

### Grafana
- URL: `https://grafana.acertaexpress.app`
- Container: `acerta-express-grafana-wo1exi-grafana-1`

### Proxmox local (Acerta Express, CPD) — host do scraper
- IP local: `192.168.18.7`
- IP Tailscale: `100.95.157.80` (interface web `https://100.95.157.80:8006`)
- SSH: `root` (senha fora do git)
- Hardware: Intel i7-6700K, 46GB RAM, storages `local`/`local-lvm`/`ssd1`/`ssd2`/`hdd1tb`
- **LXC 105 `ares-predator`** (Debian 13, 2 vCPU, 4GB RAM, IP `192.168.18.49`): roda o scraper em produção (`/opt/ares-predator`, sync via rsync do Mac — não é git repo dentro do container)
- Outras VMs/LXC no mesmo node: VM 100 `ubuntu`, VM 101 `w11`, VM 103 `haos18-2` (Home Assistant), LXC 102 `uptime-kuma`

## Brudam

### Acesso Web
- URL: `https://acertaexpress.brudam.com.br`
- Usuário: `FELIPE CARVALHO`
- Senha: `(ver .env — fora do git)`
- **Atenção:** acesso restrito ao Brasil (geo-bloqueio)

### API (tela 669)
- Endpoint login: `POST https://acertaexpress.brudam.com.br/api/v1/acesso/auth/login`
- Usuário API: `2d8ef5476fab725a5bf9271b474046ff`
- Senha API: `0511ed411169dc642a423b3f272ca82359c5146150b0d064752dcff0a5218fd9`
- Token: `7ea3bb473fe7519c43dc64552492e62c252cffcce43ca41b04`
- **Obs:** API tem endpoints limitados (tracking, CTe, faturas). Os relatórios do BI são via web scraping.

### Relatórios mapeados

| Código | URL | Método | Tabela | Notas |
|--------|-----|---------|--------|-------|
| 106 | `/opr/relatorio/emissoes` | POST (form) | `emissoes` | Filtro **SEM RECEBEDOR** (notas em trânsito); start_date `01/01/2026` |
| 129 | `/operacional/lista_ctes_cia.php` | POST (form) | `awbs` | Últimos 7 dias |
| 138 | `/brd/ger/unidade/get-trechos` | GET | `coletas` | — |
| 147 | (atalho) Custo por Operação | POST (form) via Playwright | `custos_operacao` | start_date `01/01/2026`; Brudam recusa janelas grandes e trunca em 10k → backfill (`custos_operacao_historico`) em chunks de 1 mês, **upsert por MINUTA** (idempotente, sem TRUNCATE) |
| 295 | `/sac/lista_reclamacao.php` | GET | `canhotos` | Últimos 30 dias |
| 314 | `/operacional/perecivel.php` | POST (form) | `pereciveis` | Últimos 30 dias |
| 399 | `/operacional/lista_agendamentos.php` | POST (form) | `remessas` | Janela default do Brudam |
| 027 | (atalho) Cotações | POST (form) | `cotacoes` | start_date `01/01/2026` via JS direto nos inputs |

### Login via Playwright
- Endpoint interno: `POST /brd/sys/login/tms`
- Campos do form: `#user` e `#password`
- Após login, cookies importantes: `uidbrd`, `globaluidbrd`, `usuario`, `id_usuario`, `base`, `unidade`, `grupo`
- Playwright funcionou e retornou todos os cookies corretamente

## Status Atual

### O que está rodando em produção
- [x] PostgreSQL na VPS (porta 5433) com banco `ares_bi`
- [x] Scraper roda no **LXC 105 (`ares-predator`) no Proxmox local**, CPD da Acerta Express (Brasil) — VPS é geo-bloqueada. Migrado do Mac em 2026-09; Mac não roda mais nenhum cron do projeto (sync, smoke tests e backfill 147 saíram de lá — SPOF resolvido)
- [x] Cron no LXC 105: sync 15 min durante o dia (6h-22h), a cada ~1h30 durante a noite; backfill 147 mensal (dia 1, 5h) e refresh 147 recente diário (23h); smoke tests horário (ver `/etc/cron.d/ares-predator` dentro do container)
- [x] 8 tabelas populadas pelo sync: `emissoes`, `coletas`, `cotacoes`, `remessas`, `awbs`, `canhotos`, `pereciveis`, `custos_operacao` (+ `sync_log`)
- [x] Tabela `custos_operacao_historico` populada por backfill mensal (cron dia 1 às 5:00 BR — ver `run-backfill-147.sh`)
- [x] Grafana operacional em `https://grafana.acertaexpress.app`
- [x] Dashboard web ARES em `https://ares.acertaexpress.app` (`ares-web`, repo separado em `~/ACERTA/ares-web`)

### Tabelas e responsabilidade

| Tabela | Origem | Estratégia |
|---|---|---|
| `emissoes` | sync diário, 106 SEM RECEBEDOR | UPSERT por MINUTA + delete de minutas fora do relatório |
| `coletas`, `cotacoes`, `remessas`, `awbs`, `canhotos`, `pereciveis`, `custos_operacao` | sync diário | TRUNCATE + INSERT JSONB |
| `custos_operacao_historico` | `backfill_147.py` manual/cron mensal | **UPSERT por MINUTA** (chunked, idempotente) — índice único `uq_custos_operacao_historico_minuta`. SEM TRUNCATE: rodar 2x não duplica nem apaga histórico. |
| `sync_log` | sync diário | INSERT por execução |

### Pendência aberta
- Nenhuma no momento. (Card 5 do Painel Comercial foi calibrado em 2026-06-12: soma bruta da coluna `AF — LUCRO LIQ` do relatório 147 triplicava por subtítulos/subtotais/totalizador-final do Brudam — fix filtra por `MINUTA` com 6+ dígitos e `DATA` no formato `DD/MM/YYYY`. Valor real do trimestre Mar+Abr+Mai/26 é ~R$5,2M; o R$482k citado pela diretoria era Jan/26 isolado, não o trimestre.)

## Dependências Python
```bash
pip install playwright psycopg2-binary requests
python -m playwright install chromium
```

## Repositório
- GitHub: `https://github.com/felipesabores/ares-predator`
- Clone: `git clone https://github.com/felipesabores/ares-predator`
