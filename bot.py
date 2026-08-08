#!/usr/bin/env python3
"""
Revisa precios de criptomonedas (via CoinGecko) y notifica por Telegram.
Diseñado para ejecutarse UNA VEZ por corrida (ideal para GitHub Actions
con `schedule`), no como proceso en loop.

Configuración de alertas: config.json (editable sin tocar código).
Credenciales: variables de entorno TELEGRAM_TOKEN y TELEGRAM_CHAT_ID
              (en GitHub Actions vienen de los Secrets del repo).
Estado (para no repetir avisos): state.json, se actualiza cada corrida.
"""

import json
import os
import sys
from datetime import datetime, timezone

import requests

CONFIG_PATH = "config.json"
STATE_PATH = "state.json"

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


def cargar_json(path: str, default: dict) -> dict:
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def guardar_json(path: str, data: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# CoinGecko no usa símbolos estilo Binance (ej. "BTCUSDT"), usa un "id"
# propio por moneda. Este mapeo permite seguir usando los mismos symbols
# en config.json sin tener que cambiar nada ahí.
SYMBOL_TO_COINGECKO_ID = {
    "BTCUSDT": "bitcoin",
    "ETHUSDT": "ethereum",
    "SOLUSDT": "solana",
    "BNBUSDT": "binancecoin",
    "XRPUSDT": "ripple",
    "ADAUSDT": "cardano",
    "DOGEUSDT": "dogecoin",
}


def obtener_precio(symbol: str) -> float:
    coingecko_id = SYMBOL_TO_COINGECKO_ID.get(symbol.upper())
    if not coingecko_id:
        raise ValueError(
            f"No conozco el id de CoinGecko para '{symbol}'. "
            f"Agrégalo a SYMBOL_TO_COINGECKO_ID en bot.py "
            f"(busca el id correcto en https://api.coingecko.com/api/v3/coins/list)."
        )
    url = "https://api.coingecko.com/api/v3/simple/price"
    resp = requests.get(
        url, params={"ids": coingecko_id, "vs_currencies": "usd"}, timeout=10
    )
    resp.raise_for_status()
    return float(resp.json()[coingecko_id]["usd"])


def enviar_telegram(mensaje: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[ERROR] Falta TELEGRAM_TOKEN o TELEGRAM_CHAT_ID en las variables de entorno.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    resp = requests.post(
        url, data={"chat_id": TELEGRAM_CHAT_ID, "text": mensaje}, timeout=10
    )
    if resp.status_code != 200:
        print(f"[ERROR] No se pudo enviar el mensaje: {resp.text}")
    else:
        print(f"[OK] Mensaje enviado: {mensaje!r}")


def main():
    config = cargar_json(CONFIG_PATH, {"notificar_siempre": False, "alertas": []})
    state = cargar_json(STATE_PATH, {})

    ahora = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # Cache de precios ya consultados en esta corrida (por si hay varias
    # alertas con el mismo symbol, no pedirlo a CoinGecko más de una vez)
    precios_cache = {}

    def get_precio_cached(symbol):
        if symbol not in precios_cache:
            precios_cache[symbol] = obtener_precio(symbol)
        return precios_cache[symbol]

    # --- Notificación "siempre" (precio actual, sin condición) ---
    if config.get("notificar_siempre"):
        symbols = {a["symbol"] for a in config.get("alertas", [])} or {"BTCUSDT"}
        for symbol in symbols:
            precio = get_precio_cached(symbol)
            enviar_telegram(f"₿ {symbol}: ${precio:,.2f}\n🕒 {ahora}")

    # --- Alertas por umbral ---
    for alerta in config.get("alertas", []):
        if not alerta.get("activa", True):
            continue

        alerta_id = alerta["id"]
        symbol = alerta["symbol"]
        condicion = alerta["condicion"]  # "arriba" o "abajo"
        umbral = alerta["precio"]

        precio = get_precio_cached(symbol)
        cruzado = (
            precio >= umbral if condicion == "arriba" else precio <= umbral
        )
        ya_avisado = state.get(alerta_id, False)

        if cruzado and not ya_avisado:
            emoji = "🚀" if condicion == "arriba" else "📉"
            palabra = "superó" if condicion == "arriba" else "cayó por debajo de"
            enviar_telegram(
                f"{emoji} ¡{symbol} {palabra} ${umbral:,.2f}!\n"
                f"Precio actual: ${precio:,.2f}\n"
                f"🕒 {ahora}"
            )
            state[alerta_id] = True
        elif not cruzado and ya_avisado:
            # El precio volvió a cruzar en sentido contrario: reseteamos
            # para que si vuelve a cruzar el umbral, avise de nuevo.
            state[alerta_id] = False

        print(f"[{alerta_id}] {symbol}={precio} umbral={umbral} "
              f"condicion={condicion} cruzado={cruzado} ya_avisado={ya_avisado}")

    guardar_json(STATE_PATH, state)


if __name__ == "__main__":
    try:
        main()
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Fallo de conexión: {e}")
        sys.exit(1)
