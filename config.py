"""Configuración central.

Todos los secretos llegan como variables de entorno inyectadas por el
workflow de GitHub Actions (GitHub Secrets), sin depender de ningún
gestor de secretos de nube de pago.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def _get_env(name: str, default: str | None = None, *, required: bool = False) -> str:
    value = os.environ.get(name, default)
    if required and (value is None or value == ""):
        raise RuntimeError(f"Falta la variable de entorno obligatoria: {name}")
    return value if value is not None else ""


def _get_int_env(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        value = default
    else:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            logger.warning("Valor no entero para %s=%r; usando %d", name, raw, default)
            value = default
    return max(minimum, min(maximum, value))


# --- Configuración general ---------------------------------------------------

GEMINI_MODEL: str = _get_env("GEMINI_MODEL", "gemini-2.5-flash-lite")
IMPORTANCE_THRESHOLD: int = _get_int_env("IMPORTANCE_THRESHOLD", 7, minimum=0, maximum=10)
MAX_EMAIL_CHARACTERS: int = _get_int_env(
    "MAX_EMAIL_CHARACTERS", 12000, minimum=500, maximum=100000
)

LOG_LEVEL: str = _get_env("LOG_LEVEL", "INFO")

# Scopes mínimos de Gmail. gmail.readonly basta para history.list.
GMAIL_SCOPES: list[str] = ["https://www.googleapis.com/auth/gmail.readonly"]

HTTP_TIMEOUT_SECONDS: int = 30

# TTL de los mensajes procesados guardados para deduplicación (30 días).
PROCESSED_MESSAGE_TTL_SECONDS: int = 30 * 24 * 60 * 60


def configure_logging() -> None:
    """Configura logging global según LOG_LEVEL, sin duplicar handlers."""
    level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(levelname)s %(name)s %(message)s",
    )
    logging.getLogger().setLevel(level)


def get_gmail_token_json() -> str:
    return _get_env("GMAIL_OAUTH_TOKEN_JSON", required=True)


def get_gemini_api_key() -> str:
    return _get_env("GEMINI_API_KEY", required=True)


def get_telegram_bot_token() -> str:
    return _get_env("TELEGRAM_BOT_TOKEN", required=True)


def get_telegram_chat_id() -> str:
    return _get_env("TELEGRAM_CHAT_ID", required=True)


def get_upstash_redis_rest_url() -> str:
    return _get_env("UPSTASH_REDIS_REST_URL", required=True)


def get_upstash_redis_rest_token() -> str:
    return _get_env("UPSTASH_REDIS_REST_TOKEN", required=True)
