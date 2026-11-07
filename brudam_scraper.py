"""
Brudam Scraper - Acerta Express BI
Extrai dados do Brudam e salva no PostgreSQL da VPS.
Roda a cada 30 minutos via Windows Task Scheduler.
"""

import os
import requests
import psycopg2
import json
import logging
from datetime import datetime, timedelta
from urllib.parse import quote
from playwright.sync_api import sync_playwright

# Permite usar Chromium do sistema em distros não suportadas pelo Playwright
_CHROMIUM_PATH = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH") or None

# ─── Configurações ────────────────────────────────────────────
BRUDAM_URL   = "https://acertaexpress.brudam.com.br"
from src.settings import brudam_credentials, db_config
BRUDAM_USER, BRUDAM_PASS = brudam_credentials()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ─── Login via Playwright ──────────────────────────────────────
def get_session_cookies():
    log.info("Fazendo login no Brudam...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, **( {"executable_path": _CHROMIUM_PATH} if _CHROMIUM_PATH else {} ))
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto(BRUDAM_URL, wait_until="networkidle", timeout=30000)

        # Preenche usuário e senha
        page.fill("#user", BRUDAM_USER)
        page.fill("#password", BRUDAM_PASS)
        page.click("#acessar")

        # Aguarda redirecionamento pós-login
        page.wait_for_url(lambda url: "/dashboard" in url or url != BRUDAM_URL + "/",
                          timeout=20000)

        cookies = {c["name"]: c["value"] for c in ctx.cookies()}
        browser.close()

    log.info(f"Login OK. Cookies: {list(cookies.keys())}")
    return cookies

# ─── Busca relatório ───────────────────────────────────────────
def fetch_report(session, url, method="POST", data=None):
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": url,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    log.info(f"  -> {method} {url} ...")
    r = session.request(method, url, data=data, headers=headers, timeout=120)
    log.info(f"  -> {r.status_code} | {len(r.text)} bytes")
    if r.status_code != 200:
        log.warning(f"{url} -> {r.status_code}")
        return None
    try:
        return r.json()
    except:
        return {"raw_html": r.text}

# ─── Database ──────────────────────────────────────────────────
def get_db():
    return psycopg2.connect(**db_config())

def init_db():
    log.info("Inicializando banco de dados...")
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS emissoes (
            id_minuta       TEXT PRIMARY KEY,
            house           TEXT,
            sigla_unidade   TEXT,
            data_emissao    DATE,
            coleta          TEXT,
            coleta_data     DATE,
            cte_numero      TEXT,
            id_manifesto    TEXT,
            c_fantasia      TEXT,
            r_fantasia      TEXT,
            r_cidade        TEXT,
            r_uf            TEXT,
            d_fantasia      TEXT,
            r_endereco      TEXT,
            d_endereco      TEXT,
            entrega_resp    TEXT,
            frete_total     NUMERIC(12,2),
            tipo_cte_cod    TEXT,
            cte_status_cod  TEXT,
            resp_entrega_dest TEXT,
            atualizado_em   TIMESTAMP DEFAULT NOW()
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS agendamentos (
            id_minuta       VARCHAR(20),
            dados           JSONB,
            atualizado_em   TIMESTAMP DEFAULT NOW(),
            PRIMARY KEY (id_minuta)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS pereciveis (
            id_minuta       VARCHAR(20),
            dados           JSONB,
            atualizado_em   TIMESTAMP DEFAULT NOW(),
            PRIMARY KEY (id_minuta)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS ctes_cia (
            id              SERIAL PRIMARY KEY,
            dados           JSONB,
            atualizado_em   TIMESTAMP DEFAULT NOW()
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS sac_reclamacoes (
            id              SERIAL PRIMARY KEY,
            dados           JSONB,
            atualizado_em   TIMESTAMP DEFAULT NOW()
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS sync_log (
            id              SERIAL PRIMARY KEY,
            relatorio       VARCHAR(50),
            registros       INTEGER,
            status          VARCHAR(20),
            erro            TEXT,
            executado_em    TIMESTAMP DEFAULT NOW()
        )
    """)

    conn.commit()
    cur.close()
    conn.close()
    log.info("Banco inicializado.")

def log_sync(relatorio, registros, status, erro=None):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO sync_log (relatorio, registros, status, erro)
        VALUES (%s, %s, %s, %s)
    """, (relatorio, registros, status, erro))
    conn.commit()
    cur.close()
    conn.close()

# ─── Parsers ───────────────────────────────────────────────────
def parse_date(s):
    if not s:
        return None
    for fmt in ["%d/%m/%Y", "%Y-%m-%d"]:
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except:
            pass
    return None

def parse_decimal(s):
    if not s:
        return None
    try:
        return float(str(s).replace(".", "").replace(",", "."))
    except:
        return None

def save_emissoes(data):
    if not data or data.get("status") != "1":
        log.warning("Emissoes: dados inválidos")
        return 0

    rows = data.get("dados", [])
    if len(rows) < 2:
        return 0

    headers = rows[0]
    records = rows[1:]

    conn = get_db()
    cur = conn.cursor()
    count = 0

    batch = []
    for row in records:
        d = dict(zip(headers, row))
        batch.append((
            d.get("id_minuta"), d.get("house"), d.get("sigla_unidade"),
            parse_date(d.get("data")), d.get("coleta"),
            parse_date(d.get("coleta_data")), d.get("cte_numero"),
            d.get("id_manifesto"), d.get("c_fantasia"),
            d.get("r_fantasia"), d.get("r_cidade"), d.get("r_uf"),
            d.get("d_fantasia"), d.get("r_endereco"), d.get("d_endereco"),
            d.get("entrega_resp"), parse_decimal(d.get("frete_total")),
            d.get("tipo_cte_cod"), d.get("cte_status_cod"),
            d.get("resp_entrega_dest"),
        ))

    try:
        cur.executemany("""
            INSERT INTO emissoes (
                id_minuta, house, sigla_unidade, data_emissao, coleta,
                coleta_data, cte_numero, id_manifesto, c_fantasia,
                r_fantasia, r_cidade, r_uf, d_fantasia, r_endereco,
                d_endereco, entrega_resp, frete_total, tipo_cte_cod,
                cte_status_cod, resp_entrega_dest, atualizado_em
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, NOW())
            ON CONFLICT (id_minuta) DO UPDATE SET
                cte_status_cod    = EXCLUDED.cte_status_cod,
                entrega_resp      = EXCLUDED.entrega_resp,
                frete_total       = EXCLUDED.frete_total,
                atualizado_em     = NOW()
        """, batch)
        conn.commit()
        count = len(batch)
    except Exception as e:
        conn.rollback()
        log.error(f"Erro ao salvar emissoes em lote: {e}")

    conn.commit()
    cur.close()
    conn.close()
    return count

def save_json_table(table, data):
    """Salva dados genéricos como JSONB."""
    if not data:
        return 0
    conn = get_db()
    cur = conn.cursor()
    cur.execute(f"DELETE FROM {table}")
    payload = json.dumps(data, ensure_ascii=False)
    cur.execute(f"INSERT INTO {table} (dados) VALUES (%s)", (payload,))
    conn.commit()
    cur.close()
    conn.close()
    return 1

# ─── Main ──────────────────────────────────────────────────────
def run():
    hoje = datetime.now().strftime("%d/%m/%Y")
    inicio = (datetime.now() - timedelta(days=30)).strftime("%d/%m/%Y")

    init_db()
    cookies = get_session_cookies()

    session = requests.Session()
    for k, v in cookies.items():
        session.cookies.set(k, v)

    relatorios = [
        {
            "nome": "emissoes",
            "url": f"{BRUDAM_URL}/opr/relatorio/emissoes",
            "method": "POST",
            "data": (
                f"method=search&situacao=2&tipo_data=data&dt_inicio={quote(inicio)}&dt_fim={quote(hoje)}"
                "&minuta_status=9999&cte_status=8888&tipo_cte=99&tipo_emissao=0&tipo_pagamento=0"
                "&resp_coleta_tipo=0&faturamento=0&servico=0&tabela=a&id_tabela=0"
                "&resp_entrega_tipo=0&ordem=id_minuta&emissor=0&cte_emissor=0&centro_custo=0"
                "&manifesto=0&hora_inicial=00%3A00&hora_final=23%3A59&tipo_origem=0&tipo_destino=0"
                "&tipo_cadastro=id_cliente&coluna=f.fantasia&tipo_cadastro_2=id_cliente&coluna_2=f.fantasia"
                "&serv=&nome=&unidade=&nome_2=&campo_busca=&resp_coleta=&cte_unidade="
                "&transf_origem=&transf_destino=&resp_entrega=&acompanhante="
                "&cidade_origem=&cidade_destino=&rota=0&cc_origem=&cc_destino="
                "&check=&columns=&header=&ufs=&base_resp=&seguradora="
                "&numero_pesquisa_documento=&tipo_pesquisa_documento=&servnotin="
            ),
        },
        {
            "nome": "agendamentos",
            "url": f"{BRUDAM_URL}/operacional/lista_agendamentos.php",
            "method": "POST",
            "data": (
                f"tipo_cadastro=id_cliente&tipoNota=nf&tipoCampo=coleta_numero&tipo_coluna=ff.fantasia"
                f"&minuta=&notaFiscal=&cte=&house=&buscaGeral=&buscaGeralAte=&cte_status=8888"
                f"&unidade=0&rota=0&agendamento=0&cliente_nome=&tipo_data=data&asc_desc=desc"
                f"&RespEntregaTipo=2&data_1={quote(inicio)}&data_2={quote(hoje)}&situacao=0"
                "&ordem=id_minuta&trechoIda=&trechoVolta=&respEntregaCampo=&regiao=0&PESQUISAR=PESQUISAR"
            ),
        },
        {
            "nome": "pereciveis",
            "url": f"{BRUDAM_URL}/operacional/perecivel.php",
            "method": "POST",
            "data": (
                f"tipo_cadastro=id_cliente&filtroCampo=id_minuta&tipoNota=nf&tipoCampo=coleta_numero"
                f"&tipo_coluna=ff.fantasia&minuta=&notaFiscal=&cte=&house=&cte_status=8888"
                f"&unidade=0&rota=0&agendamento=0&unidadeRespCliente=0&cliente_nome="
                f"&tipo_data=data&asc_desc=desc&RespEntregaTipo=2&data_1={quote(inicio)}"
                f"&data_2={quote(hoje)}&situacao=0&ordem=id_minuta&trechoIda=&trechoVolta="
                "&respEntregaCampo=&regiao=0&PESQUISAR=PESQUISAR"
            ),
        },
        {
            "nome": "sac",
            "url": f"{BRUDAM_URL}/sac/lista_reclamacao.php",
            "method": "GET",
            "data": None,
        },
        {
            "nome": "ctes_cia",
            "url": f"{BRUDAM_URL}/operacional/lista_ctes_cia.php",
            "method": "POST",
            "data": (
                f"order_by_query=n.id_nota+DESC&tipo_cadastro=fornecedor&tipo_coluna=fantasia"
                f"&codigo=&voo=&empresa=&unidade=0&status=1&tipoBusca=awb&buscaMinuta=id_minuta"
                f"&documento=&minuta=&perecivel=99&tipo_data=nf_data&data_inicial={quote(inicio)}"
                f"&data_final={quote(hoje)}&servico=0&retirado=0&ordem=0"
                "&numero_pesquisa_documento=&tipo_pesquisa_documento=&filtro_ocorrencias="
            ),
        },
    ]

    for rel in relatorios:
        log.info(f"Buscando relatório: {rel['nome']}...")
        try:
            data = fetch_report(session, rel["url"], rel["method"], rel.get("data"))
            if rel["nome"] == "emissoes":
                count = save_emissoes(data)
            else:
                count = save_json_table(rel["nome"] if rel["nome"] != "sac" else "sac_reclamacoes",
                                        data)
            log.info(f"  {rel['nome']}: {count} registros salvos")
            log_sync(rel["nome"], count, "ok")
        except Exception as e:
            log.error(f"  {rel['nome']}: ERRO - {e}")
            log_sync(rel["nome"], 0, "erro", str(e))

    log.info("Extração concluída.")

if __name__ == "__main__":
    run()
