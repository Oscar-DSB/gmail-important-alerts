# 📬 gmail-important-alerts

**Deja que Gemini lea tu bandeja de entrada y te avise por Telegram solo cuando de verdad importa.**

Un bot personal que vigila tu Gmail, usa Gemini para puntuar la importancia de cada correo nuevo (0-10) y te manda una alerta a Telegram si supera el umbral que tú definas. Corre 100% en la nube, gratis, **sin tarjeta de crédito en ningún servicio**.

Creado por [Oscar De Simone](https://github.com/Oscar-DSB).

---

## Por qué existe

La mayoría de arquitecturas "serverless" de correo (Gmail → Pub/Sub → Cloud Functions → Firestore) exigen una cuenta de facturación de Google Cloud, aunque el uso real caiga siempre dentro del tier gratuito. Este proyecto evita eso por completo: sustituye Pub/Sub, Firestore, Secret Manager y Cloud Scheduler por **GitHub Actions + Upstash Redis + GitHub Secrets**, todos con planes gratuitos que no piden método de pago.

El precio a pagar: en vez de una notificación push instantánea, el sistema **consulta Gmail cada 30 minutos** (configurable). Para un asistente personal de "no se me pase nada importante", es un intercambio razonable.

## Cómo funciona

```
Gmail (historyId incremental)
        │
        ▼
GitHub Actions (cron cada 30 min)
        │
        ├── Gmail API → mensajes nuevos desde el último historyId
        │
        ├── Filtros locales → descarta newsletters/publicidad sin gastar tokens
        │
        ├── Gemini API → puntúa importancia 0-10 + categoría + urgencia
        │
        ├── Upstash Redis → estado (historyId) y deduplicación de mensajes
        │
        └── Telegram Bot API → alerta solo si score >= umbral
```

No hay servidor que mantener encendido, ni watch() de Gmail que renovar: la sincronización incremental por `historyId` funciona igual con o sin suscripción push activa.

## Características

- **Clasificación inteligente**: Gemini decide qué es realmente importante (entrevistas, fechas límite, universidad, pagos, seguridad) y descarta ruido (newsletters, promociones), sin depender solo de reglas fijas.
- **Filtros locales gratis**: antes de llamar a Gemini, un filtro de palabras clave descarta lo obviamente promocional, ahorrando llamadas al modelo.
- **Idempotente**: reprocesar la misma ventana de correos nunca duplica una alerta. Si Gemini falla en un mensaje, no se marca como procesado y se reintenta automáticamente en el siguiente ciclo.
- **Autocurativo**: si el `historyId` guardado caduca (Gmail solo guarda ~7 días de historial), el sistema se reinicializa solo desde el perfil actual, sin reprocesar toda la bandeja.
- **Sin secretos en el código**: todo vive en GitHub Secrets, inyectado como variables de entorno en tiempo de ejecución.
- **32 tests automatizados**: parser MIME, filtros, clasificador (con mocks, sin llamadas reales a APIs externas) y el cliente de estado.

## Stack

Python 3.12 · Gmail API (OAuth 2.0) · Gemini API (`gemini-2.5-flash-lite`) · Telegram Bot API · Upstash Redis · GitHub Actions · BeautifulSoup4 · pytest

## Estructura

```
gmail-important-alerts/
├── main.py                     # poll_once(): entrypoint del cron
├── gmail_service.py            # Gmail API: credenciales, history.list
├── gmail_parser.py             # Parser MIME → texto plano
├── filters.py                  # Filtros locales (descarte sin llamar a Gemini)
├── importance_classifier.py    # Clasificación con Gemini + validación
├── telegram_service.py         # Envío y formato de alertas
├── state_service.py            # Estado, historyId, duplicados (Upstash Redis)
├── config.py                   # Configuración y variables de entorno
├── requirements.txt
├── .env.example
├── .github/workflows/poll.yml  # Cron (por defecto cada 30 min)
├── scripts/
│   ├── setup_gmail_oauth.py      # Genera el token OAuth local
│   └── setup_github_secrets.sh   # Sube los secretos al repo de GitHub
└── tests/
```

## Cómo montarlo tú mismo

Necesitas cuatro cuentas gratuitas, ninguna pide tarjeta: Google Cloud (solo para las credenciales OAuth de Gmail, sin facturación), [Upstash](https://console.upstash.com), [Google AI Studio](https://aistudio.google.com/apikey) y Telegram.

### 1. Credenciales de Gmail (sin facturación)

1. Crea un proyecto en [Google Cloud Console](https://console.cloud.google.com/projectcreate).
2. Habilita la API de Gmail: `gcloud services enable gmail.googleapis.com`.
3. Configura la pantalla de consentimiento OAuth (tipo Externo, modo Testing, añádete como usuario de prueba).
4. Crea credenciales **OAuth 2.0 → Aplicación de escritorio** y descarga el JSON como `credentials.json` en la raíz del proyecto.

### 2. Genera el token de Gmail

```bash
pip install -r requirements.txt
python scripts/setup_gmail_oauth.py
```

Autoriza en el navegador. Genera `gmail_token.json`.

### 3. Base de datos de estado (Upstash Redis)

Crea una base de datos Redis gratuita en [console.upstash.com](https://console.upstash.com) y copia el **REST URL** y **REST TOKEN**.

### 4. API key de Gemini

Genera una clave gratuita en [aistudio.google.com/apikey](https://aistudio.google.com/apikey).

### 5. Bot de Telegram

Habla con [@BotFather](https://t.me/BotFather) → `/newbot` → guarda el token. Envía `/start` a tu bot y consigue tu `chat_id` visitando `https://api.telegram.org/bot<TOKEN>/getUpdates`.

### 6. Sube los secretos y despliega

```bash
gh repo create tu-usuario/gmail-important-alerts --private --source=. --push

export GEMINI_API_KEY="..."
export TELEGRAM_BOT_TOKEN="..."
export TELEGRAM_CHAT_ID="..."
export UPSTASH_REDIS_REST_URL="..."
export UPSTASH_REDIS_REST_TOKEN="..."
./scripts/setup_github_secrets.sh   # sube también gmail_token.json si existe

rm gmail_token.json   # ya está en GitHub Secrets, bórralo local
```

El workflow `.github/workflows/poll.yml` se activa solo (cron). Pruébalo sin esperar:

```bash
gh workflow run poll.yml && gh run watch
```

## Personalización

| Variable | Qué controla | Default |
|---|---|---|
| `IMPORTANCE_THRESHOLD` | Score mínimo (0-10) para enviar alerta | `7` |
| `GEMINI_MODEL` | Modelo de Gemini a usar | `gemini-2.5-flash-lite` |
| `MAX_EMAIL_CHARACTERS` | Truncado del cuerpo enviado a Gemini | `12000` |
| Cron en `poll.yml` | Frecuencia de revisión | cada 30 min |

Repo privado → 2000 min/mes gratis de GitHub Actions (soporta hasta ~30 min de intervalo sin riesgo). Repo público → minutos ilimitados, permite bajar a 5-10 min.

## Tests

```bash
pytest tests/ -v
```

32 tests, todos con mocks — no llaman a Gmail, Gemini, Telegram ni Upstash reales.

## Limitaciones conocidas

- No es tiempo real: hay hasta 30 min de retraso (ajustable) frente al push de Pub/Sub.
- Pensado para una única cuenta de Gmail personal, no multi-usuario.
- El filtro de importancia es un prompt de LLM, no perfecto: puede haber falsos positivos/negativos ocasionales.

## Licencia

MIT — úsalo, modifícalo, despliega tu propia versión libremente.
