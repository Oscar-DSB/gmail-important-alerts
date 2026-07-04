"""Persistencia de estado y prevención de duplicados en Upstash Redis.

Usa la REST API de Upstash (HTTP simple con token Bearer): cada comando
Redis se envía como un array JSON en el body de un POST a la URL base,
sin añadir ningún SDK de nube de pago. Claves usadas:

  gmail_alert_state          -> JSON con last_history_id / updated_at
  processed:{message_id}     -> JSON con la clasificación del mensaje,
                                 con TTL para no acumular estado indefinido
"""

from __future__ import annotations

import json
import logging
from typing import Any

import requests

import config

logger = logging.getLogger(__name__)

STATE_KEY = "gmail_alert_state"


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {config.get_upstash_redis_rest_token()}"}


def _redis_command(*args: str) -> Any:
    """Envía un único comando Redis como array JSON a la REST API de Upstash."""
    url = config.get_upstash_redis_rest_url().rstrip("/")
    response = requests.post(
        url,
        headers=_headers(),
        json=list(args),
        timeout=config.HTTP_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json().get("result")


def get_state() -> dict[str, Any]:
    """Devuelve el documento de estado global, o {} si no existe."""
    raw = _redis_command("GET", STATE_KEY)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Estado corrupto en Upstash para %s; se ignora", STATE_KEY)
        return {}


def get_last_history_id() -> str | None:
    """Devuelve el último historyId procesado, o None si no hay estado previo."""
    state = get_state()
    value = state.get("last_history_id")
    return str(value) if value else None


def update_last_history_id(history_id: str) -> None:
    """Actualiza el last_history_id tras procesar mensajes con éxito."""
    state = get_state()
    state["last_history_id"] = str(history_id)
    _redis_command("SET", STATE_KEY, json.dumps(state))
    logger.info("Gmail state updated to historyId %s", history_id)


def is_message_processed(message_id: str) -> bool:
    """Comprueba si un mensaje ya fue procesado (idempotencia)."""
    return bool(_redis_command("EXISTS", f"processed:{message_id}"))


def mark_message_processed(
    email: dict[str, Any],
    classification: dict[str, Any],
    *,
    telegram_sent: bool,
) -> None:
    """Registra un mensaje como procesado, con su clasificación y resultado."""
    doc = {
        "message_id": email.get("message_id", ""),
        "thread_id": email.get("thread_id", ""),
        "sender": email.get("sender", ""),
        "subject": email.get("subject", ""),
        "received_at": email.get("date", ""),
        "score": classification.get("score", 0),
        "reason": classification.get("reason", ""),
        "category": classification.get("category", ""),
        "requires_action": classification.get("requires_action", False),
        "urgency": classification.get("urgency", "low"),
        "telegram_sent": telegram_sent,
    }
    message_id = email.get("message_id", "")
    _redis_command(
        "SET",
        f"processed:{message_id}",
        json.dumps(doc),
        "EX",
        str(config.PROCESSED_MESSAGE_TTL_SECONDS),
    )
