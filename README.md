```
 █████╗ ██████╗ ███████╗███████╗
██╔══██╗██╔══██╗██╔════╝██╔════╝
███████║██████╔╝█████╗  ███████╗
██╔══██║██╔══██╗██╔══╝  ╚════██║
██║  ██║██║  ██║███████╗███████║
╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝╚══════╝

██████╗ ██████╗ ███████╗██████╗  █████╗ ████████╗ ██████╗ ██████╗
██╔══██╗██╔══██╗██╔════╝██╔══██╗██╔══██╗╚══██╔══╝██╔═══██╗██╔══██╗
██████╔╝██████╔╝█████╗  ██║  ██║███████║   ██║   ██║   ██║██████╔╝
██╔═══╝ ██╔══██╗██╔══╝  ██║  ██║██╔══██║   ██║   ██║   ██║██╔══██╗
██║     ██║  ██║███████╗██████╔╝██║  ██║   ██║   ╚██████╔╝██║  ██║
╚═╝     ╚═╝  ╚═╝╚══════╝╚═════╝ ╚═╝  ╚═╝   ╚═╝    ╚═════╝ ╚═╝  ╚═╝
```

> **ARES Predator 2.** Versão 2.0 do coletor, criada a partir do `ares-predator` em 07/11/2026. Roda separado da produção (LXC própria no Proxmox, banco Postgres próprio do ARES 2.0) e alimenta o `ares-web2`. O `ares-predator` original continua em produção, intacto. Credenciais só no `.env` (ver `.env.example`).

# ARES PREDATOR

Pipeline de BI da **Acerta Express** — extrai dados operacionais do TMS Brudam via web scraping, persiste em PostgreSQL e expõe no Grafana. Sincroniza a cada 15 minutos durante o dia e a cada 1h30 durante a madrugada.

> **Atenção:** O Brudam possui geo-bloqueio. O scraper **deve ser executado a partir de um IP brasileiro** (máquina física no Brasil, não VPS europeia).

## Dashboards

| | Endereço |
|---|---|
| Dashboard Web (ARES) | **https://ares.acertaexpress.app** |
| Grafana | **https://grafana.acertaexpress.app** |


## Como funciona

```
Brudam (TMS) ──► Playwright (login) ──► Download XLSX (relatórios)
                                              │
                                              ▼
                                       PostgreSQL (VPS)
                                              │
                                              ▼
                                     Grafana (dashboards)
```

1. `sync.py` orquestra a execução
2. `brudam_scraper.py` faz login no Brudam via Playwright e extrai os relatórios
3. Os dados são processados e salvos no banco `ares_bi` via upsert
4. O Grafana lê diretamente do PostgreSQL e atualiza os dashboards

## Stack

| Camada | Tecnologia |
|---|---|
| Scraping | Python + Playwright (Chromium headless) |
| HTTP | Requests |
| Banco de dados | PostgreSQL 15 |
| Processamento | Pandas |
| Dashboards | Grafana |
| Infraestrutura | VPS Hetzner + Dokploy |
| Agendamento | cron — 15 min (dia) / 90 min (noite) |

## Relatórios extraídos

| Relatório | Tabela no banco | Descrição |
|---|---|---|
| 106 — Emissões | `emissoes` | CTes emitidos (filtro SEM RECEBEDOR — só notas em trânsito) |
| 138 — Coletas | `coletas` | Trechos e coletas |
| 027 — Cotações | `cotacoes` | Cotações |
| 399 — Remessas | `remessas` | Agendamentos e entregas |
| 129 — AWBs | `awbs` | CTes de companhias aéreas |
| 295 — Canhotos | `canhotos` | SAC e ocorrências |
| 314 — Perecíveis | `pereciveis` | Cargas perecíveis em trânsito |
| 147 — Custo por Operação | `custos_operacao` | Receita, custo e lucro líquido por op (janela 01/01/2026 → hoje) |

Além das tabelas acima, há `custos_operacao_historico` populada por backfill manual — ver seção [Backfill do 147](#backfill-do-147).

## Estrutura

```
brudam_scraper.py        # Scraper principal — login Playwright + extração
sync.py                  # Orquestrador — baixa XLSXs, processa e salva no banco
run-sync.sh              # Shell script para o cron diário
backfill_147.py          # Backfill manual do relatório 147 em chunks de 3 meses
run-backfill-147.sh      # Wrapper do cron mensal pro backfill
src/
  services/              # BrudamRobot (Playwright)
  utils/                 # Processamento de dados (Pandas)
  db/                    # Conexão e escrita no PostgreSQL
requirements.txt
```

---

## Instalação no Ubuntu Server

### 1. Atualizar o sistema

```bash
sudo apt update && sudo apt upgrade -y
```

### 2. Instalar Python 3, pip, git

```bash
sudo apt install -y python3 python3-pip python3-venv git
```

Confirme a versão (precisa ser 3.8 ou superior):

```bash
python3 --version
```

### 3. Clonar o repositório

```bash
cd ~
git clone https://github.com/felipesabores/ares-predator
cd ares-predator
```

### 4. Criar e ativar o ambiente virtual

```bash
python3 -m venv venv
source venv/bin/activate
```

O terminal vai mostrar `(venv)` antes do cursor indicando que está ativo. **Sempre que abrir um novo terminal, rode `source venv/bin/activate` antes de qualquer comando Python.**

### 5. Instalar as dependências Python

```bash
pip install -r requirements.txt
```

### 6. Instalar o Playwright e o Chromium

São **dois comandos obrigatórios** — o segundo é específico do Linux e instala as libs do sistema que o Chromium precisa:

```bash
# Baixa o browser Chromium
python -m playwright install chromium

# Instala as dependências do sistema operacional (libnss3, libatk, libgbm, etc.)
sudo python -m playwright install-deps chromium
```

Sem o segundo comando o Chromium não abre e o scraper falha imediatamente.

### 7. Verificar conexão com o banco de dados

```bash
python3 -c "
import os, psycopg2
conn = psycopg2.connect(
    host='173.249.15.221',
    port=5433,
    dbname='ares_bi',
    user='ares',
    password=os.environ['DB_PASSWORD']
)
print('Conexão OK!')
conn.close()
"
```

### 8. Testar o sync

```bash
python3 sync.py
```

A execução completa leva cerca de 3 minutos. Resultado esperado:

```
INFO ARES Sync iniciado: ...
INFO Banco inicializado.
INFO Iniciando robô Brudam...
INFO Robô finalizado.
INFO [106] -> emissoes: 954 registros salvos
INFO [138] -> coletas: 104 registros salvos
INFO [027] -> cotacoes: 4 registros salvos
INFO [399] -> remessas: 223 registros salvos
INFO [129] -> awbs: 2 registros salvos
INFO [295] -> canhotos: 794 registros salvos
INFO [314] -> pereciveis: 21 registros salvos
INFO Sync concluído: ...
```

### 9. Dar permissão ao script de execução

```bash
chmod +x ~/ares-predator/run-sync.sh
```

### 10. Configurar o cron para execução automática

```bash
crontab -e
```

Na primeira vez ele pergunta qual editor usar — escolha `1` (nano). Adicione no final do arquivo:

```cron
# ARES Predator — Noite/madrugada (21:00–06:59): a cada 1h30
0 21,0,3,6 * * * /root/ares-predator/run-sync.sh >> /root/ares-predator/sync.log 2>&1
30 22,1,4 * * * /root/ares-predator/run-sync.sh >> /root/ares-predator/sync.log 2>&1

# ARES Predator — Dia (07:00–20:59): a cada 15 min
*/15 7-20 * * * /root/ares-predator/run-sync.sh >> /root/ares-predator/sync.log 2>&1
```

> Se clonou em outro usuário, substitua `/root/` por `/home/seuusuario/`.

Salve e saia: `Ctrl+O` → `Enter` → `Ctrl+X`.

---

### Resumo — todos os comandos na ordem

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv git
cd ~
git clone https://github.com/felipesabores/ares-predator
cd ares-predator
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
sudo python -m playwright install-deps chromium
python3 sync.py
```

---

## Backfill do 147

O sync diário do relatório 147 cobre só a janela **01/01/2026 → hoje** (`custos_operacao` é truncate+insert a cada execução). Isso bastava pro Card 5 do Painel Comercial (Lucro Operacional do Último Trimestre), mas o gráfico **"Comparativo Receita Mensal × Faturamento Médio do Último Trimestre"** precisa de histórico mais longo. Daí o backfill manual.

### O que faz

`backfill_147.py` baixa o relatório 147 em **chunks de 3 meses** (Brudam recusa janelas grandes — uma única request de 17 meses volta vazia) cobrindo `01/01/2025` → hoje e popula a tabela **separada** `custos_operacao_historico`. O sync diário **não toca** nessa tabela — ela é gerenciada exclusivamente pelo backfill.

A API `/api/comercial` do `ares-web` faz UNION das 3 fontes (`custos_operacao_historico`, `custos_operacao`, `emissoes`) com `MAX(receita)` por mês — evita double-count e privilegia a fonte mais completa para cada mês.

### Quando rodar

- **Manual:** `python3 backfill_147.py` quando precisar refrescar o histórico (ex: depois de período sem rodar)
- **Agendado:** `run-backfill-147.sh` no cron, **dia 1 de cada mês às 05:00 BR** (slot natural entre os syncs das 04:30 e 06:00, sem conflito de sessão no Brudam)

### Verificar

```bash
# Volume e distribuição por mês
python3 -c "
import os, psycopg2
conn = psycopg2.connect(host='173.249.15.221', port=5433, dbname='ares_bi', user='ares', password=os.environ['DB_PASSWORD'])
cur = conn.cursor()
cur.execute('''
  SELECT TO_CHAR(TO_DATE(dados->>\\'DATA\\',\\'DD/MM/YYYY\\'),\\'YYYY-MM\\') AS mes,
         COUNT(*) AS qtd
  FROM custos_operacao_historico
  WHERE dados->>\\'DATA\\' ~ \\'^[0-9]{2}/[0-9]{2}/[0-9]{4}\$\\'
  GROUP BY mes ORDER BY mes
''')
for r in cur.fetchall(): print(r)
"

# Log da última execução (cron)
tail -50 backfill.log
```

### Tempo e tamanho

- ~8 min total (6 chunks × ~80s cada)
- ~25 MB por chunk, ~150 MB temporário em `data/raw/`
- ~56k registros pra 17 meses

### Restore

Em caso de problema, o snapshot pré-backfill original do `custos_operacao` está em `.backups/custos_operacao_*.json` (10.230 linhas no snapshot de 2026-05-27). Tags git `pre-backfill-147` em ambos os repos (`ares-predator` e `ares-web`) marcam o estado anterior.

---

## Infraestrutura

| Serviço | Endereço |
|---|---|
| VPS (Hetzner) | `173.249.15.221` |
| PostgreSQL | `173.249.15.221:5433` — banco `ares_bi` |
| Grafana | https://grafana.acertaexpress.app |
| Dokploy | `http://173.249.15.221:3000` |

---

ARES Intelligence © Acerta Express
