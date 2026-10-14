#!/usr/bin/env python3
"""Análisis heurístico BTC/USDT 1h: SMA de precio, volumen y 20 patrones."""

from datetime import datetime, timezone

import requests

BINANCE_URL = "https://data-api.binance.vision/api/v3/klines"
SYMBOL = "BTCUSDT"
INTERVAL = "1h"
LIMIT = 120
TIMEOUT = 20


def convertir_vela(fila):
    return {
        "apertura_ms": int(fila[0]),
        "open": float(fila[1]),
        "high": float(fila[2]),
        "low": float(fila[3]),
        "close": float(fila[4]),
        "volumen_btc": float(fila[5]),
        "close_ms": int(fila[6]),
        "volumen_usdt": float(fila[7]),
    }


def obtener_velas():
    """Obtiene velas cerradas; excluye la vela que Binance aún forma."""
    respuesta = requests.get(
        BINANCE_URL,
        params={"symbol": SYMBOL, "interval": INTERVAL, "limit": LIMIT},
        timeout=TIMEOUT,
    )
    respuesta.raise_for_status()
    ahora_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    velas = [
        convertir_vela(fila)
        for fila in respuesta.json()
        if int(fila[6]) < ahora_ms
    ]
    if len(velas) < 100:
        raise RuntimeError("No hay suficientes velas cerradas para SMA(99).")
    return velas


def calcular_sma(valores, periodo):
    if len(valores) < periodo:
        raise ValueError(f"Datos insuficientes para SMA({periodo}).")
    return sum(valores[-periodo:]) / periodo


def forma(vela):
    cuerpo = abs(vela["close"] - vela["open"])
    rango = max(vela["high"] - vela["low"], 1e-12)
    return {
        "cuerpo": cuerpo,
        "rango": rango,
        "superior": vela["high"] - max(vela["open"], vela["close"]),
        "inferior": min(vela["open"], vela["close"]) - vela["low"],
        "proporcion": cuerpo / rango,
    }


def alcista(v):
    return v["close"] > v["open"]


def bajista(v):
    return v["close"] < v["open"]


def tendencia_previa(velas, indice, direccion, periodo=3):
    """Compara cierres previos a la secuencia que se está evaluando."""
    if indice < periodo:
        return False
    cambio = velas[indice]["close"] - velas[indice - periodo]["close"]
    return cambio < 0 if direccion == "bajista" else cambio > 0


def detectar_patrones(velas, indice=None):
    """Detecta patrones que terminan en indice (por defecto, última vela)."""
    if indice is None:
        indice = len(velas) - 1
    if indice < 2:
        return []

    v = velas[:indice + 1]
    c = v[indice]
    fc = forma(c)
    encontrados = []

    def agregar(nombre, direccion):
        encontrados.append({"nombre": nombre, "direccion": direccion})

    # 1 Hammer / 2 Hanging Man.
    martillo = (
        fc["inferior"] >= max(fc["cuerpo"] * 2, fc["rango"] * 0.40)
        and fc["superior"] <= fc["rango"] * 0.25
        and fc["proporcion"] <= 0.40
    )
    if martillo and tendencia_previa(v, indice, "bajista"):
        agregar("Hammer (martillo)", "alcista")
    if martillo and tendencia_previa(v, indice, "alcista"):
        agregar("Hanging Man (hombre colgado)", "bajista")

    # 3 Inverted Hammer / 4 Shooting Star.
    invertido = (
        fc["superior"] >= max(fc["cuerpo"] * 2, fc["rango"] * 0.40)
        and fc["inferior"] <= fc["rango"] * 0.25
        and fc["proporcion"] <= 0.40
    )
    if invertido and tendencia_previa(v, indice, "bajista"):
        agregar("Inverted Hammer (martillo invertido)", "alcista")
    if invertido and tendencia_previa(v, indice, "alcista"):
        agregar("Shooting Star (estrella fugaz)", "bajista")

    # Patrones de dos velas.
    if indice >= 1:
        p = v[indice - 1]
        fp = forma(p)
        mitad_p = (p["open"] + p["close"]) / 2
        cuerpo_cubre = (
            min(c["open"], c["close"]) <= min(p["open"], p["close"])
            and max(c["open"], c["close"]) >= max(p["open"], p["close"])
            and fc["cuerpo"] >= fp["cuerpo"]
        )

        # 5 Bullish Engulfing / 6 Bearish Engulfing.
        if (bajista(p) and alcista(c) and cuerpo_cubre
                and tendencia_previa(v, indice - 1, "bajista")):
            agregar("Bullish Engulfing (envolvente alcista)", "alcista")
        if (alcista(p) and bajista(c) and cuerpo_cubre
                and tendencia_previa(v, indice - 1, "alcista")):
            agregar("Bearish Engulfing (envolvente bajista)", "bajista")

        # 7 Piercing Line / 8 Dark Cloud Cover.
        if (bajista(p) and alcista(c) and c["open"] <= p["close"]
                and c["close"] > mitad_p and c["close"] < p["open"]
                and tendencia_previa(v, indice - 1, "bajista")):
            agregar("Piercing Line (línea penetrante)", "alcista")
        if (alcista(p) and bajista(c) and c["open"] >= p["close"]
                and c["close"] < mitad_p and c["close"] > p["close"]
                and tendencia_previa(v, indice - 1, "alcista")):
            agregar("Dark Cloud Cover (nube oscura)", "bajista")

        # 9 Bullish Harami / 10 Bearish Harami.
        contenido = (
            min(p["open"], p["close"]) <= min(c["open"], c["close"])
            and max(c["open"], c["close"]) <= max(p["open"], p["close"])
            and fp["cuerpo"] > 0
            and fc["cuerpo"] <= fp["cuerpo"] * 0.60
        )
        if (bajista(p) and alcista(c) and contenido
                and tendencia_previa(v, indice - 1, "bajista")):
            agregar("Bullish Harami (harami alcista)", "alcista")
        if (alcista(p) and bajista(c) and contenido
                and tendencia_previa(v, indice - 1, "alcista")):
            agregar("Bearish Harami (harami bajista)", "bajista")

        # 11 Tweezer Bottom / 12 Tweezer Top; tolerancia relativa más estricta.
        tolerancia = max(c["close"] * 0.0005, (fp["rango"] + fc["rango"]) * 0.08)
        if (abs(p["low"] - c["low"]) <= tolerancia and bajista(p) and alcista(c)
                and tendencia_previa(v, indice - 1, "bajista")):
            agregar("Tweezer Bottom (suelo de pinzas)", "alcista")
        if (abs(p["high"] - c["high"]) <= tolerancia and alcista(p) and bajista(c)
                and tendencia_previa(v, indice - 1, "alcista")):
            agregar("Tweezer Top (techo de pinzas)", "bajista")

    # Patrones de tres velas.
    if indice >= 2:
        a, b, d = v[indice - 2], v[indice - 1], v[indice]
        fa, fb, fd = forma(a), forma(b), forma(d)
        mitad_a = (a["open"] + a["close"]) / 2
        b_pequena = fb["cuerpo"] <= fa["cuerpo"] * 0.60

        # 13 Morning Star / 14 Evening Star.
        if (bajista(a) and fa["proporcion"] >= 0.50 and b_pequena
                and alcista(d) and d["close"] > mitad_a
                and tendencia_previa(v, indice - 2, "bajista")):
            agregar("Morning Star (estrella de la mañana)", "alcista")
        if (alcista(a) and fa["proporcion"] >= 0.50 and b_pequena
                and bajista(d) and d["close"] < mitad_a
                and tendencia_previa(v, indice - 2, "alcista")):
            agregar("Evening Star (estrella de la tarde)", "bajista")

        # 15 Three White Soldiers / 16 Three Black Crows.
        soldados = (
            alcista(a) and alcista(b) and alcista(d)
            and a["close"] < b["close"] < d["close"]
            and min(fa["proporcion"], fb["proporcion"], fd["proporcion"]) >= 0.50
            and b["open"] >= min(a["open"], a["close"])
            and b["open"] <= max(a["open"], a["close"])
            and d["open"] >= min(b["open"], b["close"])
            and d["open"] <= max(b["open"], b["close"])
        )
        cuervos = (
            bajista(a) and bajista(b) and bajista(d)
            and a["close"] > b["close"] > d["close"]
            and min(fa["proporcion"], fb["proporcion"], fd["proporcion"]) >= 0.50
            and b["open"] <= max(a["open"], a["close"])
            and b["open"] >= min(a["open"], a["close"])
            and d["open"] <= max(b["open"], b["close"])
            and d["open"] >= min(b["open"], b["close"])
        )
        if soldados and tendencia_previa(v, indice - 2, "bajista"):
            agregar("Three White Soldiers (tres soldados blancos)", "alcista")
        if cuervos and tendencia_previa(v, indice - 2, "alcista"):
            agregar("Three Black Crows (tres cuervos negros)", "bajista")

        # 17 Three Inside Up / 18 Three Inside Down.
        interior = (
            min(a["open"], a["close"]) <= min(b["open"], b["close"])
            and max(b["open"], b["close"]) <= max(a["open"], a["close"])
            and fb["cuerpo"] <= fa["cuerpo"] * 0.60
        )
        if (bajista(a) and fa["proporcion"] >= 0.40 and interior and alcista(d)
                and d["close"] > max(a["open"], a["close"])
                and tendencia_previa(v, indice - 2, "bajista")):
            agregar("Three Inside Up (tres interiores alcistas)", "alcista")
        if (alcista(a) and fa["proporcion"] >= 0.40 and interior and bajista(d)
                and d["close"] < min(a["open"], a["close"])
                and tendencia_previa(v, indice - 2, "alcista")):
            agregar("Three Inside Down (tres interiores bajistas)", "bajista")

        # 19 Three Outside Up / 20 Three Outside Down.
        envolvente_alcista = (
            bajista(a) and alcista(b)
            and b["open"] <= a["close"] and b["close"] >= a["open"]
        )
        envolvente_bajista = (
            alcista(a) and bajista(b)
            and b["open"] >= a["close"] and b["close"] <= a["open"]
        )
        if (envolvente_alcista and alcista(d) and d["close"] > b["close"]
                and tendencia_previa(v, indice - 2, "bajista")):
            agregar("Three Outside Up (tres exteriores alcistas)", "alcista")
        if (envolvente_bajista and bajista(d) and d["close"] < b["close"]
                and tendencia_previa(v, indice - 2, "alcista")):
            agregar("Three Outside Down (tres exteriores bajistas)", "bajista")

    return encontrados


def analizar_velas(velas):
    """Analiza una secuencia que termina en una vela cerrada."""
    if len(velas) < 100:
        raise ValueError("Se necesitan al menos 100 velas cerradas.")
    cierres = [v["close"] for v in velas]
    vol_usdt = [v["volumen_usdt"] for v in velas]
    ultima = velas[-1]
    precio = ultima["close"]
    sma7 = calcular_sma(cierres, 7)
    sma25 = calcular_sma(cierres, 25)
    sma99 = calcular_sma(cierres, 99)
    ma_volumen5 = calcular_sma(vol_usdt, 5)
    ma_volumen10 = calcular_sma(vol_usdt, 10)
    volumen_actual = vol_usdt[-1]

    # Puntuar por separado precio y orden de medias.
    puntos_precio = 0.0
    if precio > sma7:
        puntos_precio += 0.5
    elif precio < sma7:
        puntos_precio -= 0.5
    if precio > sma25:
        puntos_precio += 0.75
    elif precio < sma25:
        puntos_precio -= 0.75
    if precio > sma99:
        puntos_precio += 0.5
    elif precio < sma99:
        puntos_precio -= 0.5

    if sma7 > sma25 > sma99:
        puntos_medias = 0.75
        lectura_medias = "ORDEN ALCISTA SMA7 > SMA25 > SMA99"
    elif sma7 < sma25 < sma99:
        puntos_medias = -0.75
        lectura_medias = "ORDEN BAJISTA SMA7 < SMA25 < SMA99"
    else:
        puntos_medias = 0.0
        lectura_medias = "MEDIAS SIN ORDEN CLARO"

    # El volumen describe participación; solo aporta sesgo direccional si
    # supera claramente MA(5), y la vela tiene dirección definida.
    ratio5 = volumen_actual / ma_volumen5 if ma_volumen5 else 0.0
    ratio10 = volumen_actual / ma_volumen10 if ma_volumen10 else 0.0
    if ratio5 >= 1.20 and ma_volumen5 > ma_volumen10:
        lectura_volumen = "EXPANSIÓN: volumen alto y MA(5) > MA(10)"
    elif ratio5 >= 1.20:
        lectura_volumen = "VOLUMEN ACTUAL ALTO frente a MA(5)"
    elif ratio5 <= 0.80 and ma_volumen5 < ma_volumen10:
        lectura_volumen = "CONTRACCIÓN: volumen bajo y MA(5) < MA(10)"
    elif ratio5 <= 0.80:
        lectura_volumen = "VOLUMEN ACTUAL BAJO frente a MA(5)"
    else:
        lectura_volumen = "VOLUMEN SIN DESVIACIÓN IMPORTANTE frente a MA(5)"

    puntos_volumen = 0.0
    if ratio5 >= 1.20:
        if alcista(ultima):
            puntos_volumen = 0.35
        elif bajista(ultima):
            puntos_volumen = -0.35

    patrones = detectar_patrones(velas)
    cantidad_alcista = sum(p["direccion"] == "alcista" for p in patrones)
    cantidad_bajista = sum(p["direccion"] == "bajista" for p in patrones)
    # Los patrones relacionados se limitan a un único voto neto, evitando
    # que patrones solapados (p. ej. engulfing/three outside) pesen doble.
    if cantidad_alcista > cantidad_bajista:
        puntos_patrones = 0.75
    elif cantidad_bajista > cantidad_alcista:
        puntos_patrones = -0.75
    else:
        puntos_patrones = 0.0

    puntuacion = puntos_precio + puntos_medias + puntos_volumen + puntos_patrones
    if puntuacion >= 1.50:
        conclusion = "SESGO ALCISTA"
    elif puntuacion <= -1.50:
        conclusion = "SESGO BAJISTA"
    else:
        conclusion = "MIXTA / SIN CONFIRMACIÓN"

    cierre = datetime.fromtimestamp(
        ultima["close_ms"] / 1000, tz=timezone.utc
    ).strftime("%Y-%m-%d %H:%M UTC")

    return {
        "precio": precio,
        "sma7": sma7,
        "sma25": sma25,
        "sma99": sma99,
        "lectura_medias": lectura_medias,
        "volumen_actual": volumen_actual,
        "ma_volumen5": ma_volumen5,
        "ma_volumen10": ma_volumen10,
        "ratio_volumen5": ratio5,
        "ratio_volumen10": ratio10,
        "lectura_volumen": lectura_volumen,
        "patrones": patrones,
        "alcistas": cantidad_alcista,
        "bajistas": cantidad_bajista,
        "conclusion": conclusion,
        "puntuacion": puntuacion,
        "cierre": cierre,
        "cierre_ms": ultima["close_ms"],
    }


def analizar_tendencia():
    return analizar_velas(obtener_velas())


def formatear_informe(resultado):
    lineas = [
        "📊 ANÁLISIS BTC/USDT — BINANCE SPOT",
        "Temporalidad: 1 hora",
        f"Última vela cerrada: {resultado['cierre']}",
        f"Precio de cierre: ${resultado['precio']:,.2f}",
        "",
        "📈 MEDIAS MÓVILES DE PRECIO",
        f"SMA(7): ${resultado['sma7']:,.2f}",
        f"SMA(25): ${resultado['sma25']:,.2f}",
        f"SMA(99): ${resultado['sma99']:,.2f}",
        f"Lectura: {resultado['lectura_medias']}",
        "",
        "📊 MEDIAS MÓVILES DE VOLUMEN (USDT)",
        f"Volumen última vela: ${resultado['volumen_actual']:,.2f}",
        f"MA volumen (5): ${resultado['ma_volumen5']:,.2f}",
        f"MA volumen (10): ${resultado['ma_volumen10']:,.2f}",
        f"Volumen/MA5: {resultado['ratio_volumen5']:.2f}x",
        f"Lectura: {resultado['lectura_volumen']}",
        "",
        f"🕯️ Patrones detectados: {len(resultado['patrones'])}",
    ]
    if resultado["patrones"]:
        for patron in resultado["patrones"]:
            emoji = "🟢" if patron["direccion"] == "alcista" else "🔴"
            lineas.append(f"{emoji} {patron['nombre']} — {patron['direccion']}")
    else:
        lineas.append("No se detectaron patrones de la lista en la última secuencia.")
    lineas.extend([
        "",
        f"Patrones alcistas: {resultado['alcistas']}",
        f"Patrones bajistas: {resultado['bajistas']}",
        f"Puntuación heurística: {resultado['puntuacion']:+.2f}",
        f"🧭 CONCLUSIÓN: {resultado['conclusion']}",
        "",
        "Aviso: señal heurística educativa; no predice ni garantiza movimientos futuros.",
    ])
    return "\n".join(lineas)
