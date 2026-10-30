#!/usr/bin/env python3
"""Compara tres enfoques de señales BTC/USDT 1h usando velas históricas.

A: tendencia + estructura del precio.
B: A + confirmación por volumen relativo y volatilidad.
C: B + patrón de vela de la misma dirección.

No opera ni envía Telegram. Las reglas se fijan antes de evaluar el histórico.
Los retornos son brutos, sin comisiones, spread ni deslizamiento.
"""
from __future__ import annotations

import csv
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, median

import requests
from analisis_tecnico import BINANCE_URL, SYMBOL, INTERVAL, convertir_vela, detectar_patrones

DIAS_HISTORICOS = 180
TIMEOUT = 20
TAMANO_PAGINA = 1000
HORAS_FUTURAS = (6, 12)
UMBRAL_PCT = 0.5


def descargar_historico(dias=DIAS_HISTORICOS):
    ahora_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    inicio_ms = int((datetime.now(timezone.utc) - timedelta(days=dias)).timestamp() * 1000)
    velas = []
    cursor = inicio_ms
    with requests.Session() as sesion:
        while cursor < ahora_ms:
            r = sesion.get(
                BINANCE_URL,
                params={"symbol": SYMBOL, "interval": INTERVAL, "startTime": cursor, "limit": TAMANO_PAGINA},
                timeout=TIMEOUT,
            )
            r.raise_for_status()
            filas = r.json()
            if not filas:
                break
            pagina = [convertir_vela(f) for f in filas if int(f[6]) < ahora_ms]
            pagina = [v for v in pagina if v["apertura_ms"] >= inicio_ms]
            if not pagina:
                break
            if velas:
                pagina = [v for v in pagina if v["apertura_ms"] > velas[-1]["apertura_ms"]]
            if not pagina:
                break
            velas.extend(pagina)
            cursor = velas[-1]["apertura_ms"] + 3_600_000
            time.sleep(0.12)
    unicas = {v["apertura_ms"]: v for v in velas}
    return [unicas[k] for k in sorted(unicas)]


def media(valores, periodo, fin):
    if fin + 1 < periodo:
        return None
    trozo = valores[fin - periodo + 1:fin + 1]
    return sum(trozo) / periodo


def calcular_indicadores(velas):
    cierres = [v["close"] for v in velas]
    volumenes = [v["volumen_usdt"] for v in velas]
    tr = []
    for i, v in enumerate(velas):
        if i == 0:
            tr.append(v["high"] - v["low"])
        else:
            pc = velas[i - 1]["close"]
            tr.append(max(v["high"] - v["low"], abs(v["high"] - pc), abs(v["low"] - pc)))
    atr14 = []
    atr_pct = []
    for i in range(len(velas)):
        a = media(tr, 14, i)
        atr14.append(a)
        atr_pct.append((a / cierres[i] * 100) if a is not None and cierres[i] else None)
    return cierres, volumenes, tr, atr14, atr_pct


def tendencia_y_estructura(velas, cierres, i):
    s7 = media(cierres, 7, i)
    s25 = media(cierres, 25, i)
    s99 = media(cierres, 99, i)
    s25_anterior = media(cierres, 25, i - 6)
    if None in (s7, s25, s99, s25_anterior) or i < 11:
        return 0, s7, s25, s99, False, False

    previas = velas[i - 11:i - 5]
    recientes = velas[i - 5:i + 1]
    max_prev = max(v["high"] for v in previas)
    min_prev = min(v["low"] for v in previas)
    max_rec = max(v["high"] for v in recientes)
    min_rec = min(v["low"] for v in recientes)
    maximos_crecientes = max_rec > max_prev
    minimos_crecientes = min_rec > min_prev
    minimos_decrecientes = min_rec < min_prev
    maximos_decrecientes = max_rec < max_prev

    alcista = (
        cierres[i] > s25 and s7 > s25 > s99 and s25 > s25_anterior
        and maximos_crecientes and minimos_crecientes
    )
    bajista = (
        cierres[i] < s25 and s7 < s25 < s99 and s25 < s25_anterior
        and minimos_decrecientes and maximos_decrecientes
    )
    senal = 1 if alcista else (-1 if bajista else 0)
    return senal, s7, s25, s99, maximos_crecientes and minimos_crecientes, minimos_decrecientes and maximos_decrecientes


def generar_filas(velas):
    cierres, volumenes, _, atr14, atr_pct = calcular_indicadores(velas)
    filas = []
    for i in range(110, len(velas) - max(HORAS_FUTURAS)):
        senal_a, s7, s25, s99, estructura_alcista, estructura_bajista = tendencia_y_estructura(velas, cierres, i)
        vol_ma20 = media(volumenes, 20, i)
        ratio_vol = volumenes[i] / vol_ma20 if vol_ma20 else None
        atr_pct_media20 = mean([x for x in atr_pct[i - 19:i + 1] if x is not None]) if all(x is not None for x in atr_pct[i - 19:i + 1]) else None
        volatilidad_ok = atr_pct[i] is not None and atr_pct_media20 is not None and atr_pct[i] >= atr_pct_media20
        volumen_ok = ratio_vol is not None and ratio_vol >= 1.0

        senal_b = senal_a if senal_a and volumen_ok and volatilidad_ok else 0
        patrones = detectar_patrones(velas, indice=i)
        patron_alcista = any(p["direccion"] == "alcista" for p in patrones)
        patron_bajista = any(p["direccion"] == "bajista" for p in patrones)
        patron_concordante = (senal_b == 1 and patron_alcista) or (senal_b == -1 and patron_bajista)
        senal_c = senal_b if senal_b and patron_concordante else 0

        fila = {
            "cierre_utc": datetime.fromtimestamp(velas[i]["close_ms"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "precio_cierre": velas[i]["close"],
            "sma7": s7,
            "sma25": s25,
            "sma99": s99,
            "ratio_volumen_ma20": ratio_vol,
            "atr_pct": atr_pct[i],
            "atr_pct_media20": atr_pct_media20,
            "patrones": "; ".join(p["nombre"] + " (" + p["direccion"] + ")" for p in patrones),
            "senal_A_tendencia_estructura": senal_a,
            "senal_B_mas_volatilidad_volumen": senal_b,
            "senal_C_mas_patrones": senal_c,
        }
        for h in HORAS_FUTURAS:
            futuro = velas[i + h]["close"]
            fila[f"retorno_{h}h_pct"] = (futuro / velas[i]["close"] - 1) * 100
        filas.append(fila)
    return filas


def etiqueta(retorno):
    if retorno >= UMBRAL_PCT:
        return "SUBIO"
    if retorno <= -UMBRAL_PCT:
        return "BAJO"
    return "LATERAL"


def evaluar(filas, nombre_senal, horizonte, inicio, fin, no_solapado=False):
    seleccion = filas[inicio:fin]
    if no_solapado:
        elegidas = []
        proxima = inicio
        for idx in range(inicio, fin):
            if idx < proxima:
                continue
            if int(filas[idx][nombre_senal]) != 0:
                elegidas.append(filas[idx])
                proxima = idx + horizonte
        seleccion = elegidas
    else:
        seleccion = [f for f in seleccion if int(f[nombre_senal]) != 0]

    n = len(seleccion)
    total = max(0, fin - inicio)
    retornos = [float(f[f"retorno_{horizonte}h_pct"]) for f in seleccion]
    direcciones_correctas = 0
    no_laterales = 0
    objetivos = 0
    adversos = 0
    retornos_direccionados = []
    for f, r in zip(seleccion, retornos):
        s = int(f[nombre_senal])
        resultado = etiqueta(r)
        if resultado != "LATERAL":
            no_laterales += 1
            if (s == 1 and resultado == "SUBIO") or (s == -1 and resultado == "BAJO"):
                direcciones_correctas += 1
        sr = s * r
        retornos_direccionados.append(sr)
        if sr >= UMBRAL_PCT:
            objetivos += 1
        if sr <= -UMBRAL_PCT:
            adversos += 1
    return {
        "enfoque": nombre_senal.replace("senal_", "").replace("_", " "),
        "senal": nombre_senal,
        "horizonte_h": horizonte,
        "segmento": "test_final_20pct" if inicio >= int(len(filas) * 0.8) else ("validacion_20pct" if inicio >= int(len(filas) * 0.6) else "desarrollo_60pct"),
        "seleccion": "no_solapado" if no_solapado else "todas_las_senales",
        "velas_segmento": total,
        "senales": n,
        "cobertura_pct": (n / total * 100) if total else 0,
        "acierto_direccional_solo_movimientos_no_laterales_pct": (direcciones_correctas / no_laterales * 100) if no_laterales else None,
        "porcentaje_objetivo_direccion_0_5pct_pct": (objetivos / n * 100) if n else None,
        "porcentaje_movimiento_adverso_0_5pct_pct": (adversos / n * 100) if n else None,
        "retorno_direccionado_medio_pct": mean(retornos_direccionados) if n else None,
        "retorno_direccionado_mediano_pct": median(retornos_direccionados) if n else None,
    }


def guardar_csv(ruta, filas):
    if not filas:
        raise RuntimeError(f"No hay filas para guardar en {ruta}")
    with Path(ruta).open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0].keys()))
        w.writeheader()
        w.writerows(filas)


def main():
    velas = descargar_historico()
    if len(velas) < 1000:
        raise RuntimeError(f"Histórico insuficiente: solo {len(velas)} velas.")
    filas = generar_filas(velas)
    if len(filas) < 500:
        raise RuntimeError(f"Muestra evaluable insuficiente: {len(filas)} filas.")

    n = len(filas)
    cortes = [("desarrollo_60pct", 0, int(n * 0.6)), ("validacion_20pct", int(n * 0.6), int(n * 0.8)), ("test_final_20pct", int(n * 0.8), n)]
    senales = ["senal_A_tendencia_estructura", "senal_B_mas_volatilidad_volumen", "senal_C_mas_patrones"]
    resumen = []
    for nombre, inicio, fin in cortes:
        for senal in senales:
            for h in HORAS_FUTURAS:
                resumen.append(evaluar(filas, senal, h, inicio, fin, no_solapado=False))
                resumen.append(evaluar(filas, senal, h, inicio, fin, no_solapado=True))

    # Añade referencia pasiva: mantener posición larga en todas las velas del test.
    inicio, fin = int(n * 0.8), n
    for h in HORAS_FUTURAS:
        rs = [float(f[f"retorno_{h}h_pct"]) for f in filas[inicio:fin]]
        resumen.append({
            "enfoque": "referencia_largo_siempre", "senal": "referencia_largo_siempre",
            "horizonte_h": h, "segmento": "test_final_20pct", "seleccion": "todas_las_velas",
            "velas_segmento": len(rs), "senales": len(rs), "cobertura_pct": 100.0,
            "acierto_direccional_solo_movimientos_no_laterales_pct": (sum(r >= UMBRAL_PCT for r in rs) / sum(etiqueta(r) != "LATERAL" for r in rs) * 100) if any(etiqueta(r) != "LATERAL" for r in rs) else None,
            "porcentaje_objetivo_direccion_0_5pct_pct": sum(r >= UMBRAL_PCT for r in rs) / len(rs) * 100,
            "porcentaje_movimiento_adverso_0_5pct_pct": sum(r <= -UMBRAL_PCT for r in rs) / len(rs) * 100,
            "retorno_direccionado_medio_pct": mean(rs), "retorno_direccionado_mediano_pct": median(rs),
        })

    guardar_csv("comparacion_senales_btc_1h.csv", filas)
    guardar_csv("resumen_enfoques_btc_1h.csv", resumen)
    print(f"Velas descargadas: {len(velas)}")
    print(f"Observaciones evaluables: {len(filas)}")
    print(f"Periodo: {filas[0]['cierre_utc']} a {filas[-1]['cierre_utc']}")
    print("Regla de movimiento: SUBIO >= +0.5%, BAJO <= -0.5%, resto LATERAL.")
    print("Señales: +1 alcista, -1 bajista, 0 sin señal. Retornos brutos sin costes.")
    print("Archivos: comparacion_senales_btc_1h.csv y resumen_enfoques_btc_1h.csv")
    print("\nResumen del test final (último 20% cronológico), señales no solapadas:")
    for r in resumen:
        if r["segmento"] == "test_final_20pct" and r["seleccion"] == "no_solapado":
            print(f"{r['enfoque']} | {r['horizonte_h']}h | n={r['senales']} | cobertura={r['cobertura_pct']:.1f}% | acierto direccional={r['acierto_direccional_solo_movimientos_no_laterales_pct']} | retorno dirigido medio={r['retorno_direccionado_medio_pct']}")
    print("\nNOTA: prueba exploratoria. El test final es provisional, no una garantía de generalización; reglas no optimizadas y no incluye comisiones, spread ni deslizamiento.")


if __name__ == "__main__":
    main()
