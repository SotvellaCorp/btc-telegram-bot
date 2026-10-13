
#!/usr/bin/env python3
"""
Bot de alertas de precio y análisis técnico BTC/USDT.
Se ejecuta una vez por corrida de GitHub Actions.
"""
import json
import os
import sys
from datetime import datetime, timezone

import requests
from analisis_tecnico import analizar_tendencia, formatear_informe

CONFIG_PATH = "config.json"
STATE_PATH = "state.json"

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

SYMBOL_TO_COINGECKO_ID = {
    "BTCUSDT": "bitcoin",
    "ETHUSDT": "ethereum",
    "SOLUSDT": "solana",
    "BNBUSDT": "binancecoin",
    "XRPUSDT": "ripple",
    "ADAUSDT": "cardano",
    "DOGEUSDT": "dogecoin",
}


def cargar_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as archivo:
        return json.load(archivo)


def guardar_json(path, data):
    with open(path, "w", encoding="utf-8") as archivo:
        json.dump(data, archivo, indent=2, ensure_ascii=False)


def obtener_precio(symbol):
    coin_id = SYMBOL_TO_COINGECKO_ID.get(symbol.upper())
    if not coin_id:
        raise ValueError(f"Símbolo no configurado en CoinGecko: {symbol}")

    respuesta = requests.get(
        "https://api.coingecko.com/api/v3/simple/price",
        params={"ids": coin_id, "vs_currencies": "usd"},
        timeout=10,
    )
    respuesta.raise_for_status()
    return float(respuesta.json()[coin_id]["usd"])


def enviar_telegram(mensaje):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[ERROR] Faltan TELEGRAM_TOKEN o TELEGRAM_CHAT_ID.")
        return False

    respuesta = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        data={"chat_id": TELEGRAM_CHAT_ID, "text": mensaje},
        timeout=15,
    )

    if respuesta.status_code != 200:
        print(f"[ERROR] Telegram respondió HTTP {respuesta.status_code}: {respuesta.text}")
        return False

    print("[OK] Mensaje enviado a Telegram.")
    return True


def main():
    config = cargar_json(
        CONFIG_PATH,
        {"notificar_siempre": False, "alertas": [], "analisis_tecnico": True},
    )
    estado = cargar_json(STATE_PATH, {})
    ahora = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    precios_cache = {}

    def precio_cacheado(symbol):
        if symbol not in precios_cache:
            precios_cache[symbol] = obtener_precio(symbol)
        return precios_cache[symbol]

    # Notificación opcional del precio actual.
    if config.get("notificar_siempre", False):
        simbolos = {a["symbol"] for a in config.get("alertas", [])} or {"BTCUSDT"}
        for symbol in simbolos:
            try:
                precio = precio_cacheado(symbol)
                enviar_telegram(f"₿ {symbol}: ${precio:,.2f}\n🕒 {ahora}")
            except (requests.exceptions.RequestException, KeyError, ValueError) as error:
                print(f"[ERROR] Precio de {symbol}: {error}")

    # Alertas por umbral originales.
    for alerta in config.get("alertas", []):
        if not alerta.get("activa", True):
            continue

        alerta_id = alerta["id"]
        symbol = alerta["symbol"]
        condicion = alerta["condicion"]
        umbral = float(alerta["precio"])

        try:
            precio = precio_cacheado(symbol)
        except (requests.exceptions.RequestException, KeyError, ValueError) as error:
            print(f"[ERROR] No se pudo consultar {symbol}: {error}")
            continue

        cruzado = precio >= umbral if condicion == "arriba" else precio <= umbral
        ya_avisado = estado.get(alerta_id, False)

        if cruzado and not ya_avisado:
            emoji = "🚀" if condicion == "arriba" else "📉"
            palabra = "superó" if condicion == "arriba" else "cayó por debajo de"
            enviado = enviar_telegram(
                f"{emoji} ¡{symbol} {palabra} ${umbral:,.2f}!\n"
                f"Precio actual: ${precio:,.2f}\n🕒 {ahora}"
            )
            if enviado:
                estado[alerta_id] = True

        elif not cruzado and ya_avisado:
            estado[alerta_id] = False

        print(
            f"[{alerta_id}] {symbol}={precio} umbral={umbral} "
            f"condicion={condicion} cruzado={cruzado} ya_avisado={ya_avisado}"
        )

    # Análisis técnico: solo un informe por cada nueva vela horaria cerrada.
    if config.get("analisis_tecnico", True):
        try:
            resultado = analizar_tendencia()
            ultima_vela = resultado["cierre_ms"]
            vela_previa = estado.get("ultima_vela_analizada_btc_1h")

            if ultima_vela != vela_previa:
                enviado = enviar_telegram(formatear_informe(resultado))
                if enviado:
                    estado["ultima_vela_analizada_btc_1h"] = ultima_vela
            else:
                print("[INFO] Esta vela ya fue analizada.")

        except (
            requests.exceptions.RequestException,
            ValueError,
            RuntimeError,
            KeyError,
        ) as error:
            print(f"[ERROR] Falló el análisis técnico: {error}")

    guardar_json(STATE_PATH, estado)


if __name__ == "__main__":
    try:
        main()
    except requests.exceptions.RequestException as error:
        print(f"[ERROR] Fallo de conexión: {error}")
        sys.exit(1)
