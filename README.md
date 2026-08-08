# BTC Telegram Bot (GitHub Actions)

Revisa el precio de BTC (u otras monedas) en CoinGecko cada 5 minutos usando
GitHub Actions, y avisa por Telegram cuando se cumple una condición.

> **Nota:** este bot usaba antes la API de Binance, pero Binance bloquea
> las conexiones desde IPs de Estados Unidos (incluyendo los servidores de
> GitHub Actions). Por eso ahora usa la API pública de CoinGecko, que no
> tiene ese bloqueo.

## 1. Crear el repositorio

Sube estos archivos a un repositorio de GitHub (puede ser privado).

## 2. Crear tu bot de Telegram

1. Habla con [@BotFather](https://t.me/BotFather) en Telegram.
2. Envía `/newbot` y sigue las instrucciones. Te dará un **token**.
3. Envíale cualquier mensaje a tu bot recién creado (ej. "hola").
4. Abre en el navegador:
   `https://api.telegram.org/bot<TU_TOKEN>/getUpdates`
5. Busca `"chat":{"id":123456789,...}` — ese número es tu **chat id**.

## 3. Configurar los Secrets en GitHub

En tu repo: **Settings → Secrets and variables → Actions → New repository secret**

- `TELEGRAM_TOKEN` → el token del paso anterior
- `TELEGRAM_CHAT_ID` → tu chat id

Nunca pongas estos valores directamente en el código: por eso van como Secrets.

## 4. Editar `config.json`

Ahí defines qué quieres monitorear, sin tocar el código:

```json
{
  "notificar_siempre": false,
  "alertas": [
    {
      "id": "btc_arriba_70000",
      "symbol": "BTCUSDT",
      "condicion": "arriba",
      "precio": 70000,
      "activa": true
    }
  ]
}
```

- `symbol`: uno de los símbolos que el bot ya reconoce: `BTCUSDT`, `ETHUSDT`,
  `SOLUSDT`, `BNBUSDT`, `XRPUSDT`, `ADAUSDT`, `DOGEUSDT`. Internamente el
  bot traduce esto a un "id" de CoinGecko (ej. `BTCUSDT` → `bitcoin`). Si
  quieres agregar otra moneda que no esté en la lista, hay que agregarla
  al diccionario `SYMBOL_TO_COINGECKO_ID` en `bot.py` (el id correcto se
  busca en https://api.coingecko.com/api/v3/coins/list).
- `condicion`: `"arriba"` o `"abajo"`
- `precio`: el umbral que dispara la alerta
- `activa`: pon `false` para desactivar una alerta sin borrarla
- `id`: identificador único (se usa para recordar si ya se avisó)
- `notificar_siempre`: si es `true`, además de las alertas, te manda el
  precio actual de todos los símbolos configurados en cada corrida
  (ojo: esto sí te escribe cada 5 minutos sin parar)

Para agregar una alerta nueva, solo agrega otro bloque al array `alertas`.

## 5. Activar el workflow

El archivo `.github/workflows/check_price.yml` ya viene listo. Al subir el
repo, GitHub Actions empezará a correrlo automáticamente cada 5 minutos.

También puedes probarlo manualmente: pestaña **Actions** → selecciona el
workflow → **Run workflow**.

## 6. Cómo evita el spam

Cada alerta se dispara **una sola vez** al cruzar el umbral. Si el precio
vuelve a cruzarlo en sentido contrario, la alerta se "rearma" y puede
volver a avisar si se cruza de nuevo. Esto se guarda en `state.json`, que
el workflow actualiza con un commit automático después de cada corrida.

## Ideas para ampliarlo

- Agregar más monedas (solo agrega alertas con otro `symbol`)
- Cambiar el mensaje para incluir % de variación en 24h
  (CoinGecko soporta esto agregando `include_24hr_change=true` al request)
- Enviar un resumen diario en vez de solo alertas puntuales
- Agregar alertas por volumen o variación porcentual repentina
