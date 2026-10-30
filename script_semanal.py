#!/usr/bin/env python3
"""
Recolha semanal de dados para a empresa fictícia de investimento.

Faz só três coisas:
  1. Fechos oficiais dos instrumentos acompanhados  -> dados/precos.csv
  2. Benchmark VWCE com reforços mensais (reconstruído do zero em cada execução)
                                                    -> dados/benchmark.csv
                                                    -> dados/benchmark_reforcos.csv
  3. Notícias recentes (Google News RSS)            -> dados/noticias.csv
E deixa um resumo da execução (com avisos) em dados/estado.json.

"Fecho oficial" = fecho de um dia ANTERIOR à data de execução (data UTC).
O workflow corre às 08:00 UTC, com a bolsa já aberta, por isso a barra do
próprio dia no Yahoo é intradiária e é sempre ignorada.

Não fala com a Trading 212, não toma decisões e não envia nada.
A configuração (tickers, data de início, benchmark) está em config.json.
"""

import csv
import json
import sys
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote_plus

import requests
import yfinance as yf

RAIZ = Path(__file__).resolve().parent
PASTA_DADOS = RAIZ / "dados"
CONFIG = RAIZ / "config.json"
GOOGLE_NEWS_URL = "https://news.google.com/rss/search?q={q}+when:7d&hl=en-US&gl=US&ceid=US:en"
PAUSA_S = 2  # pausa curta entre pedidos, por cortesia

AVISOS = []


def aviso(msg):
    print(f"[aviso] {msg}")
    AVISOS.append(msg)


def carregar_config():
    with open(CONFIG, encoding="utf-8") as f:
        return json.load(f)


def escrever_csv(caminho, campos, linhas):
    with open(caminho, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=campos)
        w.writeheader()
        w.writerows(linhas)


def pct(novo, antigo):
    if novo is None or not antigo:
        return ""
    return round((novo / antigo - 1) * 100, 2)


# ---------------------------------------------------------------- preços

def historico(ticker, desde, hoje):
    """Fechos oficiais diários (não ajustados) de `desde` até ao dia ANTES de `hoje`.

    Devolve [(data, fecho), ...] por ordem cronológica, ou None se o Yahoo não
    devolver nada. A barra de `hoje` (e posteriores) é descartada porque, à hora
    a que o script corre, ainda é um preço intradiário e não um fecho.
    """
    try:
        df = yf.Ticker(ticker).history(start=desde.isoformat(), end=hoje.isoformat(),
                                       auto_adjust=False)
    except Exception as e:
        aviso(f"{ticker}: erro ao obter histórico ({e})")
        return None
    if df is None or df.empty or "Close" not in df:
        aviso(f"{ticker}: sem dados devolvidos pelo Yahoo")
        return None
    fechos = df["Close"].dropna()
    pontos = sorted({ts.date(): float(v) for ts, v in fechos.items() if ts.date() < hoje}.items())
    if not pontos:
        aviso(f"{ticker}: o Yahoo não devolveu nenhum fecho oficial antes de {hoje.isoformat()}")
        return None
    return pontos


def fecho_em_ou_antes(fechos, dia):
    anteriores = [p for p in fechos if p[0] <= dia]
    return anteriores[-1] if anteriores else None


def fecho_em_ou_depois(fechos, dia):
    seguintes = [p for p in fechos if p[0] >= dia]
    return seguintes[0] if seguintes else None


def dia_util_anterior(dia):
    """Último dia de semana (seg-sex) estritamente antes de `dia`. Não conhece feriados."""
    d = dia - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def moeda(ticker):
    try:
        return getattr(yf.Ticker(ticker).fast_info, "currency", "") or ""
    except Exception:
        return ""


def recolher_precos(cfg, hoje):
    inicio = date.fromisoformat(cfg["data_inicio"])
    desde = min(inicio, hoje - timedelta(days=14)) - timedelta(days=7)
    esperado = dia_util_anterior(hoje)
    campos = ["ticker_yahoo", "nome", "tipo", "moeda", "data_fecho", "fecho",
              "var_semana_pct", "var_desde_inicio_pct", "nota"]
    linhas, cache, sucessos = [], {}, 0

    # `instrumentos` é opcional: sem ele o script trata só do ticker do benchmark.
    tickers = {i["ticker_yahoo"]: i for i in cfg.get("instrumentos") or []}
    bench = cfg["benchmark"]["ticker_yahoo"]
    tickers.setdefault(bench, {"ticker_yahoo": bench, "nome": "Benchmark", "tipo": "ETF"})

    for t, inst in tickers.items():
        base = {"ticker_yahoo": t, "nome": inst.get("nome", ""), "tipo": inst.get("tipo", "")}
        fechos = historico(t, desde, hoje)
        cache[t] = fechos
        if not fechos:
            # Linha vazia de propósito: nunca gravar um valor antigo como se fosse atual.
            linhas.append({**base, "nota": "SEM PREÇO: o Yahoo não devolveu fechos (ver avisos)"})
            continue
        ultimo = fechos[-1]
        notas = []
        if ultimo[0] < esperado:
            aviso(f"{t}: último fecho oficial é de {ultimo[0].isoformat()}, "
                  f"esperava-se {esperado.isoformat()} (preço desatualizado ou feriado)")
            notas.append(f"fecho desatualizado (esperado {esperado.isoformat()})")
        semana = fecho_em_ou_antes(fechos, ultimo[0] - timedelta(days=7))
        arranque = fecho_em_ou_depois(fechos, inicio) if inicio <= ultimo[0] else None
        m = moeda(t)
        if m not in ("EUR", ""):
            notas.append(f"cotado em {m}, não em EUR")
        linhas.append({
            **base,
            "moeda": m,
            "data_fecho": ultimo[0].isoformat(),
            "fecho": round(ultimo[1], 4),
            "var_semana_pct": pct(ultimo[1], semana[1] if semana else None),
            "var_desde_inicio_pct": pct(ultimo[1], arranque[1] if arranque else None),
            "nota": "; ".join(notas),
        })
        sucessos += 1

    escrever_csv(PASTA_DADOS / "precos.csv", campos, linhas)
    print(f"[ok] preços: {sucessos}/{len(tickers)} instrumentos")
    return cache, sucessos


# ------------------------------------------------------------- benchmark

def meses_desde(inicio_ym, ate):
    """Primeiro dia de cada mês de `inicio_ym` ("AAAA-MM") até ao mês de `ate`, inclusive."""
    ano, mes = (int(x) for x in inicio_ym.split("-"))
    d = date(ano, mes, 1)
    while d <= ate:
        yield d
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)


def calcular_tranches(b, inicio, fechos):
    """Lista de compras do benchmark: [(data, montante, preço, unidades), ...].

    - Tranche inicial: `montante_inicial_eur` ao fecho oficial de `data_inicio`
      (ou do primeiro dia de negociação a seguir, se a bolsa estiver fechada).
    - Reforços: `reforco_mensal_eur` a partir do mês `inicio_reforcos`, cada um ao
      fecho oficial do primeiro dia de negociação em ou depois do dia 1 do mês.
      Um reforço só entra quando esse fecho já existe.
    O preço de cada tranche é sempre o fecho desse dia: não depende de dados posteriores.
    """
    inicial = float(b.get("montante_inicial_eur", b.get("montante_eur", 600)))
    reforco = float(b.get("reforco_mensal_eur", 0))
    tranches = []
    primeira = fecho_em_ou_depois(fechos, inicio)
    if primeira is None:
        return tranches
    tranches.append((primeira[0], inicial, primeira[1], inicial / primeira[1]))
    if reforco > 0 and b.get("inicio_reforcos"):
        for dia1 in meses_desde(b["inicio_reforcos"], fechos[-1][0]):
            compra = fecho_em_ou_depois(fechos, dia1)
            if compra is None or compra[0] <= primeira[0]:
                continue
            tranches.append((compra[0], reforco, compra[1], reforco / compra[1]))
    return tranches


def atualizar_benchmark(cfg, hoje, cache):
    """Reconstrói benchmark.csv do zero a partir do histórico do Yahoo."""
    b = cfg["benchmark"]
    t = b["ticker_yahoo"]
    inicio = date.fromisoformat(cfg["data_inicio"])
    caminho = PASTA_DADOS / "benchmark.csv"
    caminho_tr = PASTA_DADOS / "benchmark_reforcos.csv"
    campos = ["data_fecho", "ticker_yahoo", "fecho", "capital_entregue_eur", "unidades",
              "valor_eur", "var_eur", "var_pct"]
    campos_tr = ["data_compra", "ticker_yahoo", "montante_eur", "preco_compra", "unidades"]

    if hoje <= inicio:
        print("[info] benchmark: a simulação ainda não tem fechos oficiais")
        return
    fechos = cache.get(t)
    if not fechos:
        aviso(f"benchmark: não foi possível calcular, sem preços para {t}")
        return
    fechos = [p for p in fechos if p[0] >= inicio]
    tranches = calcular_tranches(b, inicio, fechos)
    if not tranches:
        aviso(f"benchmark: não foi possível calcular, sem fecho de {t} desde {inicio.isoformat()}")
        return

    # Sinaliza se o Yahoo reviu o preço de uma compra já registada numa execução anterior.
    if caminho_tr.exists():
        with open(caminho_tr, encoding="utf-8") as f:
            antigas = {r["data_compra"]: r for r in csv.DictReader(f)}
        for d, _, preco, _ in tranches:
            r = antigas.get(d.isoformat())
            if r and r.get("preco_compra") and abs(float(r["preco_compra"]) - preco) > 0.005:
                aviso(f"benchmark: o preço de compra de {d.isoformat()} mudou no Yahoo "
                      f"({r['preco_compra']} -> {round(preco, 4)})")

    linhas = []
    for dia, fecho in fechos:
        entregue = sum(m for d, m, _, _ in tranches if d <= dia)
        unidades = sum(u for d, _, _, u in tranches if d <= dia)
        valor = unidades * fecho
        linhas.append({
            "data_fecho": dia.isoformat(),
            "ticker_yahoo": t,
            "fecho": round(fecho, 4),
            "capital_entregue_eur": round(entregue, 2),
            "unidades": round(unidades, 6),
            "valor_eur": round(valor, 2),
            "var_eur": round(valor - entregue, 2),
            "var_pct": pct(valor, entregue),
        })
    escrever_csv(caminho, campos, linhas)
    escrever_csv(caminho_tr, campos_tr, [{
        "data_compra": d.isoformat(), "ticker_yahoo": t, "montante_eur": round(m, 2),
        "preco_compra": round(p, 4), "unidades": round(u, 6)} for d, m, p, u in tranches])
    u = linhas[-1]
    print(f"[ok] benchmark: {u['data_fecho']} {u['valor_eur']}€ "
          f"para {u['capital_entregue_eur']}€ entregues ({u['var_pct']}%)")


# -------------------------------------------------------------- notícias

def parse_rss(xml_bytes):
    """Devolve [(titulo, fonte, data_str, link), ...] de um feed RSS do Google News."""
    raiz = ET.fromstring(xml_bytes)
    artigos = []
    for item in raiz.iter("item"):
        titulo_completo = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        fonte_el = item.find("source")
        fonte = (fonte_el.text or "").strip() if fonte_el is not None else ""
        # O Google News põe "Título - Fonte" no fim do título: tiramos a fonte para não duplicar.
        titulo = titulo_completo
        if fonte and titulo_completo.endswith(" - " + fonte):
            titulo = titulo_completo[: -len(fonte) - 3]
        data = ""
        try:
            data = parsedate_to_datetime(item.findtext("pubDate") or "").strftime("%Y-%m-%d %H:%M")
        except (TypeError, ValueError):
            pass
        if link:
            artigos.append((titulo, fonte, data, link))
    return artigos


def recolher_noticias(cfg, hoje):
    caminho = PASTA_DADOS / "noticias.csv"
    campos = ["pedido", "data", "titulo", "fonte", "link"]
    pedidos = cfg.get("noticias", {}).get("pesquisas", [])
    limite = int(cfg.get("noticias", {}).get("artigos_por_pesquisa", 8))
    linhas, vistos = [], set()

    for i, pesquisa in enumerate(pedidos):
        if i:
            time.sleep(PAUSA_S)
        url = GOOGLE_NEWS_URL.format(q=quote_plus(pesquisa))
        try:
            r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            artigos = parse_rss(r.content)
        except Exception as e:
            aviso(f"notícias '{pesquisa}': erro ({e})")
            continue
        apanhados = 0
        for titulo, fonte, data, link in artigos:
            if link in vistos or apanhados >= limite:
                continue
            vistos.add(link)
            apanhados += 1
            linhas.append({"pedido": pesquisa, "data": data, "titulo": titulo,
                           "fonte": fonte, "link": link})

    linhas.sort(key=lambda r: r["data"], reverse=True)
    escrever_csv(caminho, campos, linhas)
    print(f"[ok] notícias: {len(linhas)} artigos de {len(pedidos)} pesquisas")


# ------------------------------------------------------------------ main

def main(hoje=None):
    AVISOS.clear()
    cfg = carregar_config()
    PASTA_DADOS.mkdir(exist_ok=True)
    hoje = hoje or datetime.now(timezone.utc).date()

    cache, sucessos = recolher_precos(cfg, hoje)
    atualizar_benchmark(cfg, hoje, cache)
    recolher_noticias(cfg, hoje)

    estado = {
        "executado_em_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "data_referencia": hoje.isoformat(),
        "nota": "Só são usados fechos oficiais de dias anteriores à data_referencia.",
        "data_inicio_simulacao": cfg["data_inicio"],
        "avisos": AVISOS,
    }
    with open(PASTA_DADOS / "estado.json", "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)

    if sucessos == 0:
        print("[erro] nenhum preço obtido; a execução falha para não guardar dados vazios")
        sys.exit(1)


if __name__ == "__main__":
    main()
