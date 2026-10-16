#!/usr/bin/env python3
"""Validación histórica sencilla de señales BTC/USDT 1h.

No opera ni envía Telegram. Usa solo información disponible hasta cada vela
para producir una señal; después mide el retorno observado 6 y 12 horas más tarde.
"""

import csv
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from analisis_tecnico import BINANCE_URL, SYMBOL, INTERVAL, convertir_vela, analizar_velas

TIMEOUT = 20
DIAS_HISTORICOS = 180
TAMANO_PAGINA = 1000
UMBRAL_MOVIMIENTO_PCT = 0.5
HORAS_FUTURAS = (6, 12)


def descargar_historico(dias=DIAS_HISTORICOS):
    ahora = datetime.now(timezone.utc)
    inicio_ms = int((ahora - timedelta(days=dias)).timestamp() * 1000)
    ahora_ms = int(ahora.timestamp() * 1000)
    velas = []
    sesion = requests.Session()
    cursor = inicio_ms

    while cursor < ahora_ms:
        respuesta = sesion.get(
            BINANCE_URL,
            params={
                "symbol": SYMBOL,
                "interval": INTERVAL,
                "startTime": cursor,
                "limit": TAMANO_PAGINA,
            },
            timeout=TIMEOUT,
        )
        respuesta.raise_for_status()
        filas = respuesta.json()
        if not filas:
            break
        pagina = [convertir_vela(f) for f in filas if int(f[6]) < ahora_ms]
        if not pagina:
            break
        if velas and pagina[0]["apertura_ms"] <= velas[-1]["apertura_ms"]:
            pagina = [v for v in pagina if v["apertura_ms"] > velas[-1]["apertura_ms"]]
        if not pagina:
            break
        velas.extend(pagina)
        cursor = velas[-1]["apertura_ms"] + 3_600_000
        time.sleep(0.15)

    # Elimina duplicados por tiempo de apertura, conservando orden cronológico.
    unicas = {}
    for vela in velas:
        unicas[vela["apertura_ms"]] = vela
    return [unicas[k] for k in sorted(unicas)]


def etiqueta_resultado(retorno_pct):
    if retorno_pct >= UMBRAL_MOVIMIENTO_PCT:
        return "SUBIO"
    if retorno_pct <= -UMBRAL_MOVIMIENTO_PCT:
        return "BAJO"
    return "LATERAL"


def main():
    velas = descargar_historico()
    if len(velas) < 150:
        raise RuntimeError(f"Histórico insuficiente: solo {len(velas)} velas.")

    filas_salida = []
    resultados = []
    inicio = 99
    fin = len(velas) - max(HORAS_FUTURAS)
    for i in range(inicio, fin):
        # La función solo recibe datos hasta la vela i: no ve el futuro.
        resultado = analizar_velas(velas[:i + 1])
        fila = {
            "cierre_utc": datetime.fromtimestamp(
                velas[i]["close_ms"] / 1000, tz=timezone.utc
            ).strftime("%Y-%m-%d %H:%M"),
            "precio_cierre": velas[i]["close"],
            "conclusion": resultado["conclusion"],
            "puntuacion": resultado["puntuacion"],
            "patrones": "; ".join(p["nombre"] for p in resultado["patrones"]),
            "volumen_ma5_ratio": resultado["ratio_volumen5"],
        }
        for horas in HORAS_FUTURAS:
            futuro = velas[i + horas]["close"]
            retorno = (futuro / velas[i]["close"] - 1) * 100
            fila[f"retorno_{horas}h_pct"] = round(retorno, 4)
            fila[f"resultado_{horas}h"] = etiqueta_resultado(retorno)
        filas_salida.append(fila)
        resultados.append((resultado["conclusion"], fila))

    salida = Path("backtest_btc_1h.csv")
    columnas = list(filas_salida[0].keys())
    with salida.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=columnas)
        escritor.writeheader()
        escritor.writerows(filas_salida)

    print(f"Velas descargadas: {len(velas)}")
    print(f"Señales evaluadas: {len(filas_salida)}")
    print(f"Archivo CSV: {salida.resolve()}")
    print(f"Periodo: {filas_salida[0]['cierre_utc']} a {filas_salida[-1]['cierre_utc']}")
    print(
        f"Movimiento clasificado como SUBIO si retorno >= +{UMBRAL_MOVIMIENTO_PCT:.1f}%, "
        f"BAJO si <= -{UMBRAL_MOVIMIENTO_PCT:.1f}%, resto LATERAL."
    )

    for horas in HORAS_FUTURAS:
        print(f"\n--- Resultados a {horas} horas ---")
        for conclusion in ("SESGO ALCISTA", "SESGO BAJISTA", "MIXTA / SIN CONFIRMACIÓN"):
            grupo = [fila for senal, fila in resultados if senal == conclusion]
            if not grupo:
                print(f"{conclusion}: sin casos")
                continue
            retornos = [float(f[f"retorno_{horas}h_pct"]) for f in grupo]
            if conclusion == "SESGO ALCISTA":
                aciertos = sum(r >= UMBRAL_MOVIMIENTO_PCT for r in retornos)
            elif conclusion == "SESGO BAJISTA":
                aciertos = sum(r <= -UMBRAL_MOVIMIENTO_PCT for r in retornos)
            else:
                aciertos = sum(abs(r) < UMBRAL_MOVIMIENTO_PCT for r in retornos)
            promedio = sum(retornos) / len(retornos)
            tasa = aciertos / len(grupo) * 100
            print(
                f"{conclusion}: n={len(grupo)}, retorno medio={promedio:+.3f}%, "
                f"coincidencia con regla={tasa:.1f}%"
            )

    print(
        "\nIMPORTANTE: esta es una primera evaluación descriptiva, no una prueba "
        "de rentabilidad. No incluye comisiones, spread ni deslizamiento, y los "
        "umbrales no se han optimizado. No uses estos resultados para operar sin "
        "validación fuera de muestra."
    )


if __name__ == "__main__":
    main()
