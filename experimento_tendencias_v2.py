#!/usr/bin/env python3
"""Experimento independiente: tendencias BTC/USDT 1h, horizonte fijo de 6h.

No opera ni envía Telegram. Solo usa velas cerradas para generar señales.
La entrada simulada es la apertura de la vela siguiente a la señal.
La salida es el cierre de la sexta vela posterior a la entrada.
"""
from __future__ import annotations

import csv
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, median

import requests

URL = "https://data-api.binance.vision/api/v3/klines"
SYMBOL = "BTCUSDT"
INTERVAL = "1h"
DIAS = 180
TIMEOUT = 20
PAGE = 1000
HORIZONTE = 6

# Supuesto editable para prueba de sensibilidad. No representa una tarifa universal.
COSTO_TOTAL_PCT = 0.20  # coste total estimado entrada + salida, en porcentaje

def descargar():
    ahora = datetime.now(timezone.utc)
    ahora_ms = int(ahora.timestamp() * 1000)
    inicio_ms = int((ahora - timedelta(days=DIAS)).timestamp() * 1000)
    cursor = inicio_ms
    velas = []
    with requests.Session() as s:
        while cursor < ahora_ms:
            r = s.get(URL, params={
                "symbol": SYMBOL, "interval": INTERVAL,
                "startTime": cursor, "limit": PAGE
            }, timeout=TIMEOUT)
            r.raise_for_status()
            filas = r.json()
            if not filas:
                break
            pagina = []
            for f in filas:
                open_ms, close_ms = int(f[0]), int(f[6])
                if open_ms >= inicio_ms and close_ms < ahora_ms:
                    pagina.append({
                        "open_ms": open_ms, "close_ms": close_ms,
                        "open": float(f[1]), "high": float(f[2]),
                        "low": float(f[3]), "close": float(f[4]),
                        "volume": float(f[5])
                    })
            if not pagina:
                break
            if velas:
                pagina = [v for v in pagina if v["open_ms"] > velas[-1]["open_ms"]]
            if not pagina:
                break
            velas.extend(pagina)
            cursor = velas[-1]["open_ms"] + 3_600_000
            time.sleep(0.12)
    unique = {v["open_ms"]: v for v in velas}
    return [unique[k] for k in sorted(unique)]

def sma(values, period, i):
    if i + 1 < period:
        return None
    return sum(values[i-period+1:i+1]) / period

def estructura(velas, i, block=6):
    # Compara dos bloques ya cerrados, sin usar ninguna vela futura.
    prev = velas[i-2*block+1:i-block+1]
    recent = velas[i-block+1:i+1]
    if len(prev) != block or len(recent) != block:
        return False, False
    hh = max(x["high"] for x in recent) > max(x["high"] for x in prev)
    hl = min(x["low"] for x in recent) > min(x["low"] for x in prev)
    lh = max(x["high"] for x in recent) < max(x["high"] for x in prev)
    ll = min(x["low"] for x in recent) < min(x["low"] for x in prev)
    return hh and hl, lh and ll

def condiciones(velas, closes, i):
    s7, s25, s99 = (sma(closes, p, i) for p in (7, 25, 99))
    s25_old = sma(closes, 25, i-6)
    if None in (s7, s25, s99, s25_old):
        return {}
    up_structure, down_structure = estructura(velas, i)
    up_a = closes[i] > s25 and s7 > s25 > s99
    down_a = closes[i] < s25 and s7 < s25 < s99
    up_b = up_a and s25 > s25_old
    down_b = down_a and s25 < s25_old
    up_c = up_b and up_structure
    down_c = down_b and down_structure
    return {
        "A": 1 if up_a else (-1 if down_a else 0),
        "B": 1 if up_b else (-1 if down_b else 0),
        "C": 1 if up_c else (-1 if down_c else 0),
        "sma7": s7, "sma25": s25, "sma99": s99,
        "sma25_cambio_6h_pct": (s25/s25_old-1)*100 if s25_old else None,
        "estructura_alcista": up_structure,
        "estructura_bajista": down_structure,
    }

def generar(velas):
    closes = [v["close"] for v in velas]
    rows = []
    previous = {"A": 0, "B": 0, "C": 0}
    for i in range(110, len(velas)-HORIZONTE-1):
        c = condiciones(velas, closes, i)
        if not c:
            continue
        row = {
            "indice": i,
            "cierre_utc": datetime.fromtimestamp(velas[i]["close_ms"]/1000, timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "precio_cierre_senal": velas[i]["close"],
            "sma7": c["sma7"], "sma25": c["sma25"], "sma99": c["sma99"],
            "sma25_cambio_6h_pct": c["sma25_cambio_6h_pct"],
            "estructura_alcista": c["estructura_alcista"],
            "estructura_bajista": c["estructura_bajista"],
            "estado_A": c["A"], "estado_B": c["B"], "estado_C": c["C"],
        }
        # Señal solo al pasar de estado neutral/opuesto a una tendencia confirmada.
        for variant in ("A", "B", "C"):
            state = c[variant]
            row[f"senal_{variant}"] = state if state != 0 and state != previous[variant] else 0
            previous[variant] = state
        rows.append(row)
    return rows

def evaluar_trades(rows, velas, variant, start, end):
    trades = []
    last_exit = -1
    for row in rows:
        i = row["indice"]
        if i < start or i + HORIZONTE + 1 >= end:
            continue
        side = int(row[f"senal_{variant}"])
        if side == 0 or i <= last_exit:
            continue
        entry_i = i + 1
        exit_i = entry_i + HORIZONTE - 1
        entry = velas[entry_i]["open"]
        exit_price = velas[exit_i]["close"]
        gross = (exit_price / entry - 1) * 100 * side
        net = gross - COSTO_TOTAL_PCT
        path = velas[entry_i:exit_i+1]
        if side == 1:
            mfe = (max(x["high"] for x in path)/entry - 1)*100
            mae = (min(x["low"] for x in path)/entry - 1)*100
        else:
            mfe = (entry/min(x["low"] for x in path) - 1)*100
            mae = (entry/max(x["high"] for x in path) - 1)*100
        trades.append({
            "variante": variant,
            "direccion": "ALCISTA" if side == 1 else "BAJISTA",
            "cierre_senal_utc": row["cierre_utc"],
            "entrada_utc": datetime.fromtimestamp(velas[entry_i]["open_ms"]/1000, timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "salida_utc": datetime.fromtimestamp(velas[exit_i]["close_ms"]/1000, timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "precio_entrada_apertura_siguiente_vela": entry,
            "precio_salida_cierre_6a_vela": exit_price,
            "retorno_bruto_direccionado_pct": gross,
            "coste_estimado_pct": COSTO_TOTAL_PCT,
            "retorno_neto_estimado_pct": net,
            "max_movimiento_favorable_pct": mfe,
            "max_movimiento_adverso_pct": mae,
            "resultado_neto_positivo": net > 0,
        })
        last_exit = exit_i
    return trades

def max_drawdown(returns):
    equity = 1.0
    peak = 1.0
    worst = 0.0
    for r in returns:
        equity *= (1 + r/100)
        peak = max(peak, equity)
        if peak:
            worst = min(worst, (equity/peak - 1)*100)
    return worst

def resumen(trades, variant, segment, start, end):
    rs = [t["retorno_neto_estimado_pct"] for t in trades]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    return {
        "variante": variant,
        "segmento": segment,
        "velas_segmento": end-start,
        "operaciones": len(rs),
        "porcentaje_ganadoras": (len(wins)/len(rs)*100) if rs else None,
        "retorno_neto_medio_pct": mean(rs) if rs else None,
        "retorno_neto_mediano_pct": median(rs) if rs else None,
        "suma_retornos_neto_pct_no_compuesta": sum(rs) if rs else None,
        "max_drawdown_secuencia_pct": max_drawdown(rs) if rs else None,
        "ganancia_media_pct": mean(wins) if wins else None,
        "perdida_media_pct": mean(losses) if losses else None,
        "factor_ganancia_perdida": (sum(wins)/abs(sum(losses))) if losses and sum(losses) != 0 else None,
        "coste_total_estimado_pct_por_operacion": COSTO_TOTAL_PCT,
    }

def write_csv(path, rows):
    if not rows:
        raise RuntimeError(f"No hay datos para {path}")
    with Path(path).open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

def main():
    candles = descargar()
    if len(candles) < 1200:
        raise RuntimeError(f"Histórico insuficiente: {len(candles)} velas")
    rows = generar(candles)
    n = len(candles)
    cuts = [
        ("desarrollo_60pct", 0, int(n*.60)),
        ("validacion_20pct", int(n*.60), int(n*.80)),
        ("test_final_20pct", int(n*.80), n-HORIZONTE-1),
    ]
    trade_rows, summary_rows = [], []
    for segment, start, end in cuts:
        for variant in ("A", "B", "C"):
            trades = evaluar_trades(rows, candles, variant, start, end)
            for t in trades:
                t["segmento"] = segment
            trade_rows.extend(trades)
            summary_rows.append(resumen(trades, variant, segment, start, end))
    write_csv("operaciones_tendencia_btc_1h.csv", trade_rows or [{
        "variante": "", "segmento": "", "nota": "No hubo operaciones en los segmentos evaluados"
    }])
    write_csv("resumen_tendencia_btc_1h.csv", summary_rows)
    print(f"Velas cerradas descargadas: {len(candles)}")
    print(f"Observaciones con indicadores: {len(rows)}")
    print(f"Periodo UTC: {rows[0]['cierre_utc']} a {rows[-1]['cierre_utc']}")
    print(f"Horizonte: {HORIZONTE} horas; coste supuesto ida y vuelta: {COSTO_TOTAL_PCT:.2f}%")
    print("Entrada: apertura de la vela posterior a la señal. Salida: cierre tras 6 velas.")
    print("Señal: transición a estado alcista/bajista; no repite cada hora mientras persiste.")
    print("\nResumen:")
    for r in summary_rows:
        print(r)
    print("\nCSV: resumen_tendencia_btc_1h.csv y operaciones_tendencia_btc_1h.csv")
    print("Advertencia: experimento, no recomendación financiera ni prueba de rentabilidad.")

if __name__ == "__main__":
    main()
