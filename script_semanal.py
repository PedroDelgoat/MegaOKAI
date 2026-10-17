#!/usr/bin/env python3
"""
Recolha semanal de dados para a empresa fictícia de investimento.

Faz só três coisas:
  1. Preços dos instrumentos acompanhados        -> dados/precos.csv
  2. Valor da carteira benchmark (uma linha/semana) -> dados/benchmark.csv
  3. Notícias recentes (Alpha Vantage, opcional)  -> dados/noticias.csv
E deixa um resumo da execução em dados/estado.json.

Não fala com a Trading 212, não toma decisões e não envia nada.
A configuração (tickers, data de início, benchmark) está em config.json.
"""

import csv
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
import yfinance as yf

RAIZ = Path(__file__).resolve().parent
PASTA_DADOS = RAIZ / "dados"
CONFIG = RAIZ / "config.json"
ALPHA_URL = "https://www.alphavantage.co/query"
PAUSA_ALPHA_S = 13  # o plano gratuito limita pedidos por minuto

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

def historico(ticker, desde):
    """Fechos diários não ajustados desde `desde`, como lista [(data, fecho), ...]."""
    try:
        df = yf.Ticker(ticker).history(start=desde.isoformat(), auto_adjust=False)
    except Exception as e:
        aviso(f"{ticker}: erro ao obter histórico ({e})")
        return None
    if df is None or df.empty or "Close" not in df:
        aviso(f"{ticker}: sem dados devolvidos pelo Yahoo")
        return None
    fechos = df["Close"].dropna()
    return [(ts.date(), float(v)) for ts, v in fechos.items()]


def fecho_em_ou_antes(fechos, dia):
    anteriores = [p for p in fechos if p[0] <= dia]
    return anteriores[-1] if anteriores else None


def fecho_em_ou_depois(fechos, dia):
    seguintes = [p for p in fechos if p[0] >= dia]
    return seguintes[0] if seguintes else None


def moeda(ticker):
    try:
        return getattr(yf.Ticker(ticker).fast_info, "currency", "") or ""
    except Exception:
        return ""


def recolher_precos(cfg, hoje):
    inicio = date.fromisoformat(cfg["data_inicio"])
    desde = min(inicio, hoje - timedelta(days=14)) - timedelta(days=7)
    campos = ["ticker_yahoo", "nome", "tipo", "moeda", "data_fecho", "fecho",
              "var_semana_pct", "var_desde_inicio_pct", "nota"]
    linhas, cache, sucessos = [], {}, 0

    tickers = {i["ticker_yahoo"]: i for i in cfg["instrumentos"]}
    bench = cfg["benchmark"]["ticker_yahoo"]
    tickers.setdefault(bench, {"ticker_yahoo": bench, "nome": "Benchmark", "tipo": "ETF"})

    for t, inst in tickers.items():
        base = {"ticker_yahoo": t, "nome": inst.get("nome", ""), "tipo": inst.get("tipo", "")}
        fechos = historico(t, desde)
        cache[t] = fechos
        if not fechos:
            linhas.append({**base, "nota": "sem dados"})
            continue
        ultimo = fecho_em_ou_antes(fechos, hoje)
        if ultimo is None:
            linhas.append({**base, "nota": "sem fecho até hoje"})
            continue
        semana = fecho_em_ou_antes(fechos, ultimo[0] - timedelta(days=7))
        arranque = fecho_em_ou_depois(fechos, inicio) if inicio <= ultimo[0] else None
        m = moeda(t)
        nota = "" if m in ("EUR", "") else f"cotado em {m}, não em EUR"
        linhas.append({
            **base,
            "moeda": m,
            "data_fecho": ultimo[0].isoformat(),
            "fecho": round(ultimo[1], 4),
            "var_semana_pct": pct(ultimo[1], semana[1] if semana else None),
            "var_desde_inicio_pct": pct(ultimo[1], arranque[1] if arranque else None),
            "nota": nota,
        })
        sucessos += 1

    escrever_csv(PASTA_DADOS / "precos.csv", campos, linhas)
    print(f"[ok] preços: {sucessos}/{len(tickers)} instrumentos")
    return cache, sucessos


# ------------------------------------------------------------- benchmark

def atualizar_benchmark(cfg, hoje, cache):
    b = cfg["benchmark"]
    t = b["ticker_yahoo"]
    inicio = date.fromisoformat(cfg["data_inicio"])
    caminho = PASTA_DADOS / "benchmark.csv"
    campos = ["data_fecho", "ticker_yahoo", "data_compra", "preco_compra", "unidades",
              "fecho", "valor_eur", "var_eur", "var_pct"]

    if hoje < inicio:
        print("[info] benchmark: a simulação ainda não começou")
        return
    fechos = cache.get(t)
    if not fechos:
        aviso(f"benchmark: sem preços para {t}")
        return
    compra = fecho_em_ou_depois(fechos, inicio)
    ultimo = fecho_em_ou_antes(fechos, hoje)
    if compra is None or ultimo is None:
        print("[info] benchmark: ainda não há fecho desde a data de início")
        return

    montante = float(b["montante_eur"])
    unidades = montante / compra[1]
    valor = unidades * ultimo[1]
    nova = {
        "data_fecho": ultimo[0].isoformat(),
        "ticker_yahoo": t,
        "data_compra": compra[0].isoformat(),
        "preco_compra": round(compra[1], 4),
        "unidades": round(unidades, 6),
        "fecho": round(ultimo[1], 4),
        "valor_eur": round(valor, 2),
        "var_eur": round(valor - montante, 2),
        "var_pct": pct(valor, montante),
    }

    # Mantém o histórico: uma linha por data, sem duplicar se o script correr duas vezes.
    linhas = {}
    if caminho.exists():
        with open(caminho, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                linhas[r["data_fecho"]] = r
    linhas[nova["data_fecho"]] = nova
    escrever_csv(caminho, campos, [linhas[k] for k in sorted(linhas)])
    print(f"[ok] benchmark: {nova['valor_eur']}€ ({nova['var_pct']}%)")


# -------------------------------------------------------------- notícias

def data_alpha(s):
    """'20261016T143000' -> '2026-10-16 14:30'"""
    try:
        return datetime.strptime(s[:13], "%Y%m%dT%H%M").strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return s


def recolher_noticias(cfg, hoje):
    caminho = PASTA_DADOS / "noticias.csv"
    campos = ["pedido", "data", "titulo", "fonte", "sentimento", "resumo", "link"]
    chave = os.environ.get("ALPHAVANTAGE_API_KEY", "").strip()
    if not chave:
        print("[info] sem ALPHAVANTAGE_API_KEY: notícias ignoradas")
        escrever_csv(caminho, campos, [])
        return

    n = cfg.get("noticias", {})
    pedidos = [("tickers", t) for t in n.get("tickers", [])] + \
              [("topics", t) for t in n.get("topicos", [])]
    limite = int(n.get("artigos_por_pedido", 10))
    desde = (hoje - timedelta(days=7)).strftime("%Y%m%dT0000")
    linhas, vistos = [], set()

    for i, (campo, valor) in enumerate(pedidos):
        if i:
            time.sleep(PAUSA_ALPHA_S)
        params = {"function": "NEWS_SENTIMENT", campo: valor, "time_from": desde,
                  "sort": "LATEST", "limit": 50, "apikey": chave}
        try:
            r = requests.get(ALPHA_URL, params=params, timeout=30)
            r.raise_for_status()
            dados = r.json()
        except Exception as e:
            aviso(f"notícias {valor}: erro no pedido ({e})")
            continue
        if "feed" not in dados:
            msg = dados.get("Information") or dados.get("Note") or \
                  dados.get("Error Message") or "resposta inesperada"
            aviso(f"notícias {valor}: {msg}")
            continue
        for art in dados["feed"][:limite]:
            url = art.get("url", "")
            if not url or url in vistos:
                continue
            vistos.add(url)
            resumo = (art.get("summary") or "").strip().replace("\n", " ")
            linhas.append({
                "pedido": f"{'ticker' if campo == 'tickers' else 'tópico'}:{valor}",
                "data": data_alpha(art.get("time_published", "")),
                "titulo": (art.get("title") or "").strip(),
                "fonte": art.get("source", ""),
                "sentimento": art.get("overall_sentiment_label", ""),
                "resumo": resumo[:300],
                "link": url,
            })

    linhas.sort(key=lambda r: r["data"], reverse=True)
    escrever_csv(caminho, campos, linhas)
    print(f"[ok] notícias: {len(linhas)} artigos de {len(pedidos)} pedidos")


# ------------------------------------------------------------------ main

def main(hoje=None):
    cfg = carregar_config()
    PASTA_DADOS.mkdir(exist_ok=True)
    hoje = hoje or datetime.now(timezone.utc).date()

    cache, sucessos = recolher_precos(cfg, hoje)
    atualizar_benchmark(cfg, hoje, cache)
    recolher_noticias(cfg, hoje)

    estado = {
        "executado_em_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "data_referencia": hoje.isoformat(),
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
