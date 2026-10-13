
#!/usr/bin/env python3
"""Análisis técnico BTC/USDT con velas de 1 hora y SMA(7/25/99)."""

from datetime import datetime, timezone

import requests

BINANCE_URL = "https://api-gcp.binance.com/api/v3/klines"
SYMBOL = "BTCUSDT"
INTERVAL = "1h"
LIMIT = 120
TIMEOUT = 15


def obtener_velas():
    """Descarga velas cerradas de Binance Spot."""
    response = requests.get(
        BINANCE_URL,
        params={
            "symbol": SYMBOL,
            "interval": INTERVAL,
            "limit": LIMIT,
        },
        timeout=TIMEOUT,
    )
    response.raise_for_status()

    ahora_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    velas = []

    for fila in response.json():
        vela = {
            "apertura_ms": int(fila[0]),
            "open": float(fila[1]),
            "high": float(fila[2]),
            "low": float(fila[3]),
            "close": float(fila[4]),
            "close_ms": int(fila[6]),
        }

        # No utilizar la vela que Binance todavía está formando.
        if vela["close_ms"] < ahora_ms:
            velas.append(vela)

    if len(velas) < 100:
        raise RuntimeError("No hay suficientes velas cerradas para el análisis.")

    return velas


def calcular_sma(cierres, periodo):
    if len(cierres) < periodo:
        raise ValueError(f"Datos insuficientes para SMA({periodo}).")
    return sum(cierres[-periodo:]) / periodo


def forma(vela):
    cuerpo = abs(vela["close"] - vela["open"])
    rango = max(vela["high"] - vela["low"], 1e-12)
    mecha_superior = vela["high"] - max(vela["open"], vela["close"])
    mecha_inferior = min(vela["open"], vela["close"]) - vela["low"]

    return {
        "cuerpo": cuerpo,
        "rango": rango,
        "superior": mecha_superior,
        "inferior": mecha_inferior,
        "proporcion": cuerpo / rango,
    }


def alcista(v):
    return v["close"] > v["open"]


def bajista(v):
    return v["close"] < v["open"]


def tendencia_previa(velas, indice, direccion, periodo=3):
    if indice < periodo:
        return False

    actual = velas[indice]["close"]
    anterior = velas[indice - periodo]["close"]

    if direccion == "bajista":
        return actual < anterior

    return actual > anterior


def detectar_patrones(velas):
    """Devuelve patrones reconocidos en la última vela/secuencia."""
    i = len(velas) - 1
    c = velas[i]
    f = forma(c)
    encontrados = []

    def agregar(nombre, direccion):
        encontrados.append({
            "nombre": nombre,
            "direccion": direccion,
        })

    # 1. Hammer / 2. Hanging Man.
    forma_martillo = (
        f["inferior"] >= max(f["cuerpo"] * 2, f["rango"] * 0.45)
        and f["superior"] <= f["rango"] * 0.25
        and f["proporcion"] <= 0.40
    )

    if forma_martillo and tendencia_previa(velas, i, "bajista"):
        agregar("Hammer (martillo)", "alcista")

    if forma_martillo and tendencia_previa(velas, i, "alcista"):
        agregar("Hanging Man (hombre colgado)", "bajista")

    # 3. Inverted Hammer / 4. Shooting Star.
    forma_invertida = (
        f["superior"] >= max(f["cuerpo"] * 2, f["rango"] * 0.45)
        and f["inferior"] <= f["rango"] * 0.25
        and f["proporcion"] <= 0.40
    )

    if forma_invertida and tendencia_previa(velas, i, "bajista"):
        agregar("Inverted Hammer (martillo invertido)", "alcista")

    if forma_invertida and tendencia_previa(velas, i, "alcista"):
        agregar("Shooting Star (estrella fugaz)", "bajista")

    # Patrones de dos velas.
    if i >= 1:
        p = velas[i - 1]
        fp = forma(p)

        # 5. Bullish Engulfing / 6. Bearish Engulfing.
        if (
            bajista(p) and alcista(c)
            and c["open"] <= p["close"]
            and c["close"] >= p["open"]
            and tendencia_previa(velas, i - 1, "bajista")
        ):
            agregar("Bullish Engulfing (envolvente alcista)", "alcista")

        if (
            alcista(p) and bajista(c)
            and c["open"] >= p["close"]
            and c["close"] <= p["open"]
            and tendencia_previa(velas, i - 1, "alcista")
        ):
            agregar("Bearish Engulfing (envolvente bajista)", "bajista")

        punto_medio = (p["open"] + p["close"]) / 2

        # 7. Piercing Line / 8. Dark Cloud Cover.
        if (
            bajista(p) and alcista(c)
            and c["close"] > punto_medio
            and c["close"] < p["open"]
            and tendencia_previa(velas, i - 1, "bajista")
        ):
            agregar("Piercing Line (línea penetrante)", "alcista")

        if (
            alcista(p) and bajista(c)
            and c["close"] < punto_medio
            and c["close"] > p["open"]
            and tendencia_previa(velas, i - 1, "alcista")
        ):
            agregar("Dark Cloud Cover (nube oscura)", "bajista")

        # 9. Bullish Harami / 10. Bearish Harami.
        cuerpo_contenido = (
            min(p["open"], p["close"]) <= min(c["open"], c["close"])
            and max(c["open"], c["close"]) <= max(p["open"], p["close"])
            and f["cuerpo"] < fp["cuerpo"] * 0.75
        )

        if (
            bajista(p) and alcista(c) and cuerpo_contenido
            and tendencia_previa(velas, i - 1, "bajista")
        ):
            agregar("Bullish Harami (harami alcista)", "alcista")

        if (
            alcista(p) and bajista(c) and cuerpo_contenido
            and tendencia_previa(velas, i - 1, "alcista")
        ):
            agregar("Bearish Harami (harami bajista)", "bajista")

        # 11. Tweezer Bottom / 12. Tweezer Top.
        tolerancia = c["close"] * 0.0015

        if (
            abs(p["low"] - c["low"]) <= tolerancia
            and bajista(p) and alcista(c)
            and tendencia_previa(velas, i - 1, "bajista")
        ):
            agregar("Tweezer Bottom (suelo de pinzas)", "alcista")

        if (
            abs(p["high"] - c["high"]) <= tolerancia
            and alcista(p) and bajista(c)
            and tendencia_previa(velas, i - 1, "alcista")
        ):
            agregar("Tweezer Top (techo de pinzas)", "bajista")

    # Patrones de tres velas.
    if i >= 2:
        a, b, d = velas[i - 2], velas[i - 1], velas[i]
        fa, fb, fd = forma(a), forma(b), forma(d)
        punto_medio_a = (a["open"] + a["close"]) / 2

        # 13. Morning Star / 14. Evening Star.
        if (
            bajista(a) and fa["proporcion"] > 0.45
            and fb["proporcion"] < 0.35
            and alcista(d) and d["close"] > punto_medio_a
            and tendencia_previa(velas, i - 2, "bajista")
        ):
            agregar("Morning Star (estrella de la mañana)", "alcista")

        if (
            alcista(a) and fa["proporcion"] > 0.45
            and fb["proporcion"] < 0.35
            and bajista(d) and d["close"] < punto_medio_a
            and tendencia_previa(velas, i - 2, "alcista")
        ):
            agregar("Evening Star (estrella de la tarde)", "bajista")

        # 15. Three White Soldiers / 16. Three Black Crows.
        if (
            alcista(a) and alcista(b) and alcista(d)
            and a["close"] < b["close"] < d["close"]
            and fa["proporcion"] > 0.35
            and fb["proporcion"] > 0.35
            and fd["proporcion"] > 0.35
        ):
            agregar("Three White Soldiers (tres soldados blancos)", "alcista")

        if (
            bajista(a) and bajista(b) and bajista(d)
            and a["close"] > b["close"] > d["close"]
            and fa["proporcion"] > 0.35
            and fb["proporcion"] > 0.35
            and fd["proporcion"] > 0.35
        ):
            agregar("Three Black Crows (tres cuervos negros)", "bajista")

        # 17. Three Inside Up / 18. Three Inside Down.
        interior = (
            min(a["open"], a["close"]) <= min(b["open"], b["close"])
            and max(b["open"], b["close"]) <= max(a["open"], a["close"])
        )

        if (
            bajista(a) and interior and alcista(d)
            and d["close"] > max(a["open"], a["close"])
            and tendencia_previa(velas, i - 2, "bajista")
        ):
            agregar("Three Inside Up (tres interiores alcistas)", "alcista")

        if (
            alcista(a) and interior and bajista(d)
            and d["close"] < min(a["open"], a["close"])
            and tendencia_previa(velas, i - 2, "alcista")
        ):
            agregar("Three Inside Down (tres interiores bajistas)", "bajista")

        # 19. Three Outside Up / 20. Three Outside Down.
        envolvente_alcista = (
            bajista(a) and alcista(b)
            and b["open"] <= a["close"]
            and b["close"] >= a["open"]
        )
        envolvente_bajista = (
            alcista(a) and bajista(b)
            and b["open"] >= a["close"]
            and b["close"] <= a["open"]
        )

        if envolvente_alcista and alcista(d) and d["close"] > b["close"]:
            agregar("Three Outside Up (tres exteriores alcistas)", "alcista")

        if envolvente_bajista and bajista(d) and d["close"] < b["close"]:
            agregar("Three Outside Down (tres exteriores bajistas)", "bajista")

    # 20 nombres de patrones posibles; solo aparecen los que se detectan.
    return encontrados


def analizar_tendencia():
    velas = obtener_velas()
    cierres = [v["close"] for v in velas]
    ultima = velas[-1]
    precio = ultima["close"]

    sma7 = calcular_sma(cierres, 7)
    sma25 = calcular_sma(cierres, 25)
    sma99 = calcular_sma(cierres, 99)

    if precio > sma7 > sma25 > sma99:
        senal_medias = 2
        lectura_medias = "ALINEACIÓN ALCISTA"
    elif precio < sma7 < sma25 < sma99:
        senal_medias = -2
        lectura_medias = "ALINEACIÓN BAJISTA"
    else:
        senal_medias = 0
        lectura_medias = "SIN ALINEACIÓN CLARA"

    patrones = detectar_patrones(velas)
    cantidad_alcista = sum(p["direccion"] == "alcista" for p in patrones)
    cantidad_bajista = sum(p["direccion"] == "bajista" for p in patrones)

    # Las medias pesan más que un patrón individual.
    puntuacion = senal_medias + cantidad_alcista - cantidad_bajista

    if puntuacion >= 2:
        conclusion = "ALCISTA"
    elif puntuacion <= -2:
        conclusion = "BAJISTA"
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
        "patrones": patrones,
        "alcistas": cantidad_alcista,
        "bajistas": cantidad_bajista,
        "conclusion": conclusion,
        "puntuacion": puntuacion,
        "cierre": cierre,
        "cierre_ms": ultima["close_ms"],
    }


def formatear_informe(resultado):
    lineas = [
        "📊 ANÁLISIS BTC/USDT — BINANCE SPOT",
        "Temporalidad: 1 hora",
        f"Última vela cerrada: {resultado['cierre']}",
        f"Precio de cierre: ${resultado['precio']:,.2f}",
        "",
        "📈 MEDIAS MÓVILES SIMPLES",
        f"SMA(7): ${resultado['sma7']:,.2f}",
        f"SMA(25): ${resultado['sma25']:,.2f}",
        f"SMA(99): ${resultado['sma99']:,.2f}",
        f"Lectura: {resultado['lectura_medias']}",
        "",
        f"🕯️ Patrones detectados: {len(resultado['patrones'])}",
    ]

    if resultado["patrones"]:
        for patron in resultado["patrones"]:
            emoji = "🟢" if patron["direccion"] == "alcista" else "🔴"
            lineas.append(
                f"{emoji} {patron['nombre']} — {patron['direccion']}"
            )
    else:
        lineas.append("No se detectaron patrones de la lista en la última secuencia.")

    lineas.extend([
        "",
        f"Patrones alcistas: {resultado['alcistas']}",
        f"Patrones bajistas: {resultado['bajistas']}",
        f"🧭 CONCLUSIÓN: {resultado['conclusion']}",
        "",
        "Aviso: análisis heurístico educativo; no garantiza movimientos futuros.",
    ])

    return "\n".join(lineas)
