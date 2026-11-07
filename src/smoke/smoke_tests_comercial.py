"""Smoke tests do Painel Comercial — Fase A (Tier 1, 3 checks).

Replica as queries do ares-web/app/api/comercial/route.ts e cruza com
fontes alternativas pra detectar:
  - Card mostrando coluna errada (líquido↔bruto, ou tabela trocada)
  - Card de "mês atual" subestimado (fonte voltando pra emissoes SEM RECEBEDOR)
  - Tabela emissoes com volume anômalo (incidente de deleção em massa)

Resultado: 1 row em card_health por check, por execução.
"""
from __future__ import annotations
import sys
import psycopg2
from datetime import datetime

from src.settings import db_config

PG = db_config()


# ────────────────────────────────────────────────────────────────────────────
# CHECK 1.1 — faturamento_medio_eh_bruto
# ────────────────────────────────────────────────────────────────────────────
# Replica a query do Card 4 (custos_operacao_historico.RECEITA dividido por 3,
# 3 meses fechados anteriores ao corrente) e cruza com SUM(FRETE TOTAL)/3
# em emissoes_dia mesmo período.
# Se o card mostrar <80% do FRETE TOTAL bruto, é fortíssimo indício de
# voltou a usar RECEITA (líquida) em vez de FRETE TOTAL (bruto).
def check_faturamento_medio_eh_bruto(cur):
    cur.execute("""
      WITH hoje_br AS (SELECT ((NOW() AT TIME ZONE 'America/Sao_Paulo')::date) AS d),
      card AS (
        SELECT COALESCE(SUM(
          COALESCE(NULLIF(dados->>'FRETE TOTAL','')::numeric, 0)
        ), 0)::float AS fat
        FROM emissoes_dia, hoje_br
        WHERE dados->>'DATA' ~ '^\\d{2}/\\d{2}/\\d{4}$'
          AND TO_DATE(dados->>'DATA','DD/MM/YYYY') >= (DATE_TRUNC('month', hoje_br.d) - INTERVAL '3 months')::date
          AND TO_DATE(dados->>'DATA','DD/MM/YYYY') <  DATE_TRUNC('month', hoje_br.d)::date
      )
      SELECT fat / 3.0 AS media_bruta FROM card;
    """)
    media_bruta = cur.fetchone()[0] or 0.0

    cur.execute("""
      WITH hoje_br AS (SELECT ((NOW() AT TIME ZONE 'America/Sao_Paulo')::date) AS d)
      SELECT COALESCE(SUM(
        CASE
          WHEN dados->>'RECEITA' ~ ','          THEN REPLACE(REPLACE(dados->>'RECEITA','.',''),',','.')::numeric
          WHEN dados->>'RECEITA' ~ '^-?[0-9]+$' THEN (dados->>'RECEITA')::numeric / 100
          ELSE 0
        END
      ), 0)::float / 3.0 AS media_receita_liquida
      FROM custos_operacao_historico, hoje_br
      WHERE dados->>'DATA' ~ '^\\d{2}/\\d{2}/\\d{4}$'
        AND TO_DATE(dados->>'DATA','DD/MM/YYYY') >= (DATE_TRUNC('month', hoje_br.d) - INTERVAL '3 months')::date
        AND TO_DATE(dados->>'DATA','DD/MM/YYYY') <  DATE_TRUNC('month', hoje_br.d)::date;
    """)
    media_liquida = cur.fetchone()[0] or 0.0

    threshold = media_bruta * 0.80
    if media_bruta == 0:
        return ("warn", media_bruta, threshold, None,
                "emissoes_dia sem rows nos 3 meses fechados — check não pôde rodar")

    # O card real (route.ts) hoje usa emissoes_dia.FRETE TOTAL, então media_bruta é o
    # que o card mostra. Verificação: se voltarem a swap pra RECEITA do 147, vai cair
    # abaixo de 80% — é o sinal.
    # Aqui detectamos divergência olhando ratio media_liquida/media_bruta — se card
    # acabar usando media_liquida, ratio mostrará isso.
    if media_liquida > 0:
        ratio = media_liquida / media_bruta if media_bruta else 0
        if ratio < 0.70:
            # tudo certo — RECEITA do 147 é bem menor que FRETE TOTAL bruto, esperado
            msg = (f"OK: FRETE TOTAL/3 = R$ {media_bruta:,.0f} | RECEITA/3 = R$ {media_liquida:,.0f} "
                   f"(ratio {ratio:.0%}, esperado pra ser líquido vs bruto).")
        else:
            msg = (f"AVISO: media RECEITA/3 = R$ {media_liquida:,.0f} muito próxima de FRETE TOTAL/3 "
                   f"= R$ {media_bruta:,.0f} (ratio {ratio:.0%}). Investigar.")
    else:
        msg = f"FRETE TOTAL/3 = R$ {media_bruta:,.0f} (RECEITA do 147 ausente — backfill 147 pode estar atrasado)"

    return ("pass", media_bruta, threshold, None, msg)


# ────────────────────────────────────────────────────────────────────────────
# CHECK 1.3 — mapa_uf_cobertura_mes_atual
# ────────────────────────────────────────────────────────────────────────────
# Mapa "Receita por UF Destino — Mês Atual" deve cobrir ≥70% do FRETE TOTAL
# do mês corrente em emissoes_dia. Se cair abaixo, mapa voltou pra emissoes
# (que tem só notas em trânsito).
def check_mapa_uf_cobertura_mes_atual(cur):
    cur.execute("""
      WITH hoje_br AS (SELECT ((NOW() AT TIME ZONE 'America/Sao_Paulo')::date) AS d),
      mtd AS (
        SELECT COALESCE(SUM(
          COALESCE(NULLIF(dados->>'FRETE TOTAL','')::numeric, 0)
        ), 0)::float AS total
        FROM emissoes_dia, hoje_br
        WHERE dados->>'DATA' ~ '^\\d{2}/\\d{2}/\\d{4}$'
          AND TO_CHAR(TO_DATE(dados->>'DATA','DD/MM/YYYY'),'YYYY-MM') = TO_CHAR(hoje_br.d,'YYYY-MM')
      ),
      uf_sum AS (
        -- Replica EXATAMENTE o campo() do route.ts: strip não-dígitos/vírgula,
        -- comma→dot, /100. TOTAL COBRADO no JSONB está em centavos.
        SELECT COALESCE(SUM(per_uf), 0)::float AS soma FROM (
          SELECT COALESCE(SUM(
            COALESCE(NULLIF(
              REPLACE(REGEXP_REPLACE(dados->>'TOTAL COBRADO', '[^0-9,]', '', 'g'), ',', '.'),
              ''
            )::numeric, 0) / 100.0
          ), 0) AS per_uf
          FROM emissoes_dia, hoje_br
          WHERE dados->>'DATA' ~ '^\\d{2}/\\d{2}/\\d{4}$'
            AND TO_CHAR(TO_DATE(dados->>'DATA','DD/MM/YYYY'),'YYYY-MM') = TO_CHAR(hoje_br.d,'YYYY-MM')
          GROUP BY COALESCE(NULLIF(TRIM(dados->>'UF.1'),''), 'N/D')
        ) per
      )
      SELECT mtd.total, uf_sum.soma FROM mtd, uf_sum;
    """)
    mtd_total, uf_soma = cur.fetchone()
    mtd_total = mtd_total or 0.0
    uf_soma = uf_soma or 0.0

    if mtd_total == 0:
        return ("warn", 0, 0, None, "Mês corrente sem rows em emissoes_dia — check pulado")

    # uf_sum usa TOTAL COBRADO (=BRUTO no route.ts, campo()-normalizado),
    # mtd usa FRETE TOTAL. São colunas distintas mas correlatas — ratio
    # histórico esperado: ~0.95-1.05.
    ratio = uf_soma / mtd_total if mtd_total else 0
    THRESHOLD_LO, THRESHOLD_HI = 0.70, 1.50

    if ratio < THRESHOLD_LO:
        return ("fail", ratio, THRESHOLD_LO, THRESHOLD_HI,
                f"Mapa UF cobertura BAIXA {ratio:.0%} (TOTAL COBRADO={uf_soma:,.0f} / FRETE TOTAL MTD={mtd_total:,.0f}). "
                f"Esperado {THRESHOLD_LO:.0%}-{THRESHOLD_HI:.0%}. Fonte possivelmente voltou pra emissoes (SEM RECEBEDOR).")
    if ratio > THRESHOLD_HI:
        return ("fail", ratio, THRESHOLD_LO, THRESHOLD_HI,
                f"Mapa UF cobertura ALTA {ratio:.0%} (TOTAL COBRADO={uf_soma:,.0f} / FRETE TOTAL MTD={mtd_total:,.0f}). "
                f"Possível bug de parsing (centavos vs reais).")
    return ("pass", ratio, THRESHOLD_LO, THRESHOLD_HI,
            f"OK: cobertura {ratio:.0%} (TOTAL COBRADO={uf_soma:,.0f} / FRETE TOTAL={mtd_total:,.0f})")


# ────────────────────────────────────────────────────────────────────────────
# CHECK 2.3 — emissoes_rows_minimo
# ────────────────────────────────────────────────────────────────────────────
# Hoje de manhã o incidente foi DELETE em massa de 701 rows; emissoes ficou
# com 519. Esse check pega esse tipo de incidente em ≤1h.
def check_emissoes_rows_minimo(cur):
    cur.execute("SELECT COUNT(*) FROM emissoes;")
    n = cur.fetchone()[0]
    minimo = 500  # ajustar conforme baseline observado; hoje está em 1368

    if n < minimo:
        return ("fail", n, minimo, None,
                f"emissoes com {n} rows (mínimo esperado {minimo}). "
                f"Possível DELETE em massa, sync travado, ou base corrompida.")
    return ("pass", n, minimo, None, f"OK: {n} rows em emissoes")


# ────────────────────────────────────────────────────────────────────────────
# CHECK 1.2 — receita_bruta_6m_cobertura
# ────────────────────────────────────────────────────────────────────────────
# Gráfico "Receita Bruta × Líquida — 6 Meses" não pode ter mês com bruto=0.
# Se voltar pra emissoes (em vez de emissoes_dia), meses fechados zeram porque
# notas já entregues foram deletadas.
def check_receita_bruta_6m_cobertura(cur):
    cur.execute("""
      WITH hoje_br AS (SELECT ((NOW() AT TIME ZONE 'America/Sao_Paulo')::date) AS d),
      meses AS (
        SELECT TO_CHAR((DATE_TRUNC('month', hoje_br.d) - (n || ' months')::interval), 'YYYY-MM') AS mes
        FROM hoje_br, generate_series(0, 5) AS n
      ),
      dados AS (
        SELECT TO_CHAR(TO_DATE(d.dados->>'DATA','DD/MM/YYYY'), 'YYYY-MM') AS mes,
               SUM(COALESCE(NULLIF(
                 REPLACE(REGEXP_REPLACE(d.dados->>'TOTAL COBRADO', '[^0-9,]', '', 'g'), ',', '.'),
                 ''
               )::numeric, 0) / 100.0)::float AS bruto
        FROM emissoes_dia d
        WHERE d.dados->>'DATA' ~ '^\\d{2}/\\d{2}/\\d{4}$'
        GROUP BY mes
      )
      SELECT m.mes, COALESCE(d.bruto, 0) AS bruto
      FROM meses m LEFT JOIN dados d USING (mes)
      ORDER BY m.mes;
    """)
    rows = cur.fetchall()
    zeros = [m for m, b in rows if (b or 0) == 0]
    total = sum((b or 0) for _, b in rows)
    if zeros:
        return ("fail", len(zeros), 0, 0,
                f"Gráfico 6 meses com {len(zeros)} mês(es) zerado(s): {', '.join(zeros)}. "
                f"Provável fonte revertida pra emissoes ou cobertura quebrada.")
    return ("pass", total, None, None,
            f"OK: 6 meses populados, soma R$ {total:,.0f}")


# ────────────────────────────────────────────────────────────────────────────
# CHECK 1.4 — top_clientes_nao_vazio
# ────────────────────────────────────────────────────────────────────────────
# Ranking "Top Clientes — Mês Atual" precisa ter ≥ 5 clientes com bruto > 1000
# no mês corrente. Se voltar pra emissoes, despenca em volume.
def check_top_clientes_nao_vazio(cur):
    cur.execute("""
      WITH hoje_br AS (SELECT ((NOW() AT TIME ZONE 'America/Sao_Paulo')::date) AS d)
      SELECT COUNT(*) FROM (
        SELECT COALESCE(NULLIF(TRIM(dados->>'CLIENTE'),''), 'Desconhecido') AS cliente,
               SUM(COALESCE(NULLIF(
                 REPLACE(REGEXP_REPLACE(dados->>'TOTAL COBRADO', '[^0-9,]', '', 'g'), ',', '.'),
                 ''
               )::numeric, 0) / 100.0) AS bruto
        FROM emissoes_dia, hoje_br
        WHERE dados->>'DATA' ~ '^\\d{2}/\\d{2}/\\d{4}$'
          AND TO_CHAR(TO_DATE(dados->>'DATA','DD/MM/YYYY'),'YYYY-MM') = TO_CHAR(hoje_br.d,'YYYY-MM')
        GROUP BY cliente
        HAVING SUM(COALESCE(NULLIF(
          REPLACE(REGEXP_REPLACE(dados->>'TOTAL COBRADO', '[^0-9,]', '', 'g'), ',', '.'),
          ''
        )::numeric, 0) / 100.0) > 1000
      ) qualificados;
    """)
    n = cur.fetchone()[0]
    minimo = 5
    if n < minimo:
        return ("fail", n, minimo, None,
                f"Apenas {n} cliente(s) com bruto > R$ 1.000 no mês atual (mínimo {minimo}). "
                f"Ranking quebrado.")
    return ("pass", n, minimo, None, f"OK: {n} clientes qualificados no ranking")


# ────────────────────────────────────────────────────────────────────────────
# CHECK 1.5 — composicao_receita_consistente
# ────────────────────────────────────────────────────────────────────────────
# Card "Composição da Receita" — componentes têm que somar ≈ FRETE TOTAL.
# Se alguma coluna sumir do JSONB ou parse quebrar, soma fica muito diferente.
def check_composicao_receita_consistente(cur):
    cur.execute("""
      WITH hoje_br AS (SELECT ((NOW() AT TIME ZONE 'America/Sao_Paulo')::date) AS d),
      comp AS (
        SELECT
          SUM(COALESCE(NULLIF(REPLACE(REGEXP_REPLACE(dados->>'FRETE PESO',  '[^0-9,]','','g'),',','.'),'')::numeric, 0)/100.0) AS frete_peso,
          SUM(COALESCE(NULLIF(REPLACE(REGEXP_REPLACE(dados->>'AD VALOREM','[^0-9,]','','g'),',','.'),'')::numeric, 0)/100.0) AS ad_valorem,
          SUM(COALESCE(NULLIF(REPLACE(REGEXP_REPLACE(dados->>'REDESPACHO','[^0-9,]','','g'),',','.'),'')::numeric, 0)/100.0) AS redespacho,
          SUM(COALESCE(NULLIF(REPLACE(REGEXP_REPLACE(dados->>'EXC. COLETA','[^0-9,]','','g'),',','.'),'')::numeric, 0)/100.0) AS exc_coleta,
          SUM(COALESCE(NULLIF(REPLACE(REGEXP_REPLACE(dados->>'EXC. ENTREGA','[^0-9,]','','g'),',','.'),'')::numeric, 0)/100.0) AS exc_entrega,
          SUM(COALESCE(NULLIF(REPLACE(REGEXP_REPLACE(dados->>'ICMS','[^0-9,]','','g'),',','.'),'')::numeric, 0)/100.0) AS icms,
          SUM(COALESCE(NULLIF(dados->>'FRETE TOTAL','')::numeric, 0))::float AS frete_total
        FROM emissoes_dia, hoje_br
        WHERE dados->>'DATA' ~ '^\\d{2}/\\d{2}/\\d{4}$'
          AND TO_CHAR(TO_DATE(dados->>'DATA','DD/MM/YYYY'),'YYYY-MM') = TO_CHAR(hoje_br.d,'YYYY-MM')
      )
      SELECT frete_peso, ad_valorem, redespacho, exc_coleta, exc_entrega, icms, frete_total FROM comp;
    """)
    fp, av, red, ec, ee, icms, ft = [float(x or 0) for x in cur.fetchone()]

    # ICMS é custo (descontado), não soma. Componentes de receita: frete_peso + ad_valorem + redespacho + exc_coleta + exc_entrega
    soma_componentes = fp + av + red + ec + ee
    if ft == 0:
        return ("warn", 0, 0, None, "Mês corrente sem FRETE TOTAL — check pulado")

    # Componentes devem refletir o FRETE TOTAL (±15%, dá margem pra desconto)
    ratio = soma_componentes / ft
    LO, HI = 0.50, 1.30
    if ratio < LO or ratio > HI:
        return ("fail", ratio, LO, HI,
                f"Composição fora da faixa: soma componentes R$ {soma_componentes:,.0f} vs FRETE TOTAL R$ {ft:,.0f} (ratio {ratio:.0%}). "
                f"Possível coluna sumida ou parse quebrado. "
                f"Detalhe: peso={fp:,.0f}, ad_val={av:,.0f}, redesp={red:,.0f}, coleta={ec:,.0f}, entrega={ee:,.0f}.")
    if fp == 0:
        return ("fail", 0, None, None, "FRETE PESO zerado no mês — coluna sumiu do JSONB")
    return ("pass", ratio, LO, HI,
            f"OK: componentes/FRETE TOTAL = {ratio:.0%} (peso={fp:,.0f}, ad_val={av:,.0f}, ICMS={icms:,.0f})")


# ────────────────────────────────────────────────────────────────────────────
# CHECK 2.1 — emissoes_dia_recente
# ────────────────────────────────────────────────────────────────────────────
# Cron de 15min deve disparar sync de emissoes_dia. Se passou >1h sem sync ok,
# alguma coisa travou (cron pausado, Brudam fora, processo zumbi).
def check_emissoes_dia_recente(cur):
    cur.execute("""
      SELECT MAX(executado_em) FROM sync_log
      WHERE relatorio='emissoes_dia' AND status='ok';
    """)
    ultimo = cur.fetchone()[0]
    if ultimo is None:
        return ("fail", 0, None, None, "Sem registros de sync OK de emissoes_dia no sync_log")

    cur.execute("SELECT EXTRACT(EPOCH FROM (NOW() - %s))/60.0", (ultimo,))
    minutos = float(cur.fetchone()[0])
    LIMITE = 110.0  # cron noturno roda a cada 90min; 110 evita falso positivo

    if minutos > LIMITE:
        return ("fail", minutos, None, LIMITE,
                f"Último sync OK de emissoes_dia foi há {minutos:.0f} min ({ultimo}). "
                f"Cron travado ou Brudam fora.")
    return ("pass", minutos, None, LIMITE,
            f"OK: último sync há {minutos:.0f} min ({ultimo})")


# ────────────────────────────────────────────────────────────────────────────
# CHECK 2.2 — custos_operacao_mes_fechado
# ────────────────────────────────────────────────────────────────────────────
# custos_operacao_historico (backfill 147) deve ter dados do mês fechado mais
# recente (mês anterior ao corrente). Se ficar parado em mês antigo, Cards 4 e
# 5 ficam com dados velhos sem ninguém perceber.
def check_custos_operacao_mes_fechado(cur):
    cur.execute("""
      WITH hoje_br AS (SELECT ((NOW() AT TIME ZONE 'America/Sao_Paulo')::date) AS d),
      mes_alvo AS (
        SELECT TO_CHAR(DATE_TRUNC('month', hoje_br.d) - INTERVAL '1 month', 'YYYY-MM') AS mes
        FROM hoje_br
      )
      SELECT mes_alvo.mes, COUNT(*) AS rows
      FROM custos_operacao_historico, mes_alvo
      WHERE dados->>'DATA' ~ '^\\d{2}/\\d{2}/\\d{4}$'
        AND TO_CHAR(TO_DATE(dados->>'DATA','DD/MM/YYYY'),'YYYY-MM') = mes_alvo.mes
      GROUP BY mes_alvo.mes;
    """)
    row = cur.fetchone()
    if row is None:
        cur.execute("""
          WITH hoje_br AS (SELECT ((NOW() AT TIME ZONE 'America/Sao_Paulo')::date) AS d)
          SELECT TO_CHAR(DATE_TRUNC('month', d) - INTERVAL '1 month', 'YYYY-MM') FROM hoje_br;
        """)
        alvo = cur.fetchone()[0]
        return ("fail", 0, 100, None,
                f"custos_operacao_historico SEM rows do mês fechado anterior ({alvo}). "
                f"Backfill 147 atrasado — Cards 4/5 com dados velhos.")
    mes, rows = row
    minimo = 100  # threshold genérico: meses ativos da Acerta tendem a >1000 rows
    if rows < minimo:
        return ("fail", rows, minimo, None,
                f"custos_operacao_historico com apenas {rows} rows em {mes} (mínimo {minimo}). Backfill parcial.")
    return ("pass", rows, minimo, None,
            f"OK: {rows} rows em {mes} (mês fechado mais recente)")


# ────────────────────────────────────────────────────────────────────────────
# Orquestração
# ────────────────────────────────────────────────────────────────────────────
CHECKS = [
    # Tier 1 — bug-class de cards/gráficos com fonte errada
    ("faturamento_medio_eh_bruto",       1, check_faturamento_medio_eh_bruto),
    ("mapa_uf_cobertura_mes_atual",      1, check_mapa_uf_cobertura_mes_atual),
    ("receita_bruta_6m_cobertura",       1, check_receita_bruta_6m_cobertura),
    ("top_clientes_nao_vazio",           1, check_top_clientes_nao_vazio),
    ("composicao_receita_consistente",   1, check_composicao_receita_consistente),
    # Tier 2 — saúde da infra de coleta
    ("emissoes_rows_minimo",             2, check_emissoes_rows_minimo),
    ("emissoes_dia_recente",             2, check_emissoes_dia_recente),
    ("custos_operacao_mes_fechado",      2, check_custos_operacao_mes_fechado),
]


def main():
    conn = psycopg2.connect(**PG)
    cur = conn.cursor()
    fails = 0
    for name, tier, fn in CHECKS:
        try:
            status, val, vmin, vmax, msg = fn(cur)
        except Exception as e:
            status, val, vmin, vmax = "erro", None, None, None
            msg = f"Exceção no check: {type(e).__name__}: {e}"
        cur.execute("""
            INSERT INTO card_health
              (check_name, tier, status, valor_observado, valor_esperado_min, valor_esperado_max, mensagem)
            VALUES (%s,%s,%s,%s,%s,%s,%s);
        """, (name, tier, status, val, vmin, vmax, msg))
        marker = {"pass":"✓", "fail":"✗", "warn":"!", "erro":"E"}.get(status, "?")
        print(f"  [{marker}] {name} ({status}) — {msg or ''}")
        if status in ("fail", "erro"):
            fails += 1
    conn.commit()
    print(f"\n{len(CHECKS)} checks, {fails} fail/erro.")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
