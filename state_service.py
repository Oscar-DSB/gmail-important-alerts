"""Persistencia de estado y prevención de duplicados en Upstash Redis.

Usa la REST API de Upstash (HTTP simple con token Bearer): cada comando
Redis se envía como un array JSON en el body de un POST a la URL base,
sin añadir ningún SDK de nube de pago. Claves usadas:

  gmail_alert_state          -> JSON con last_history_id / updated_at /
                                 telegram_update_offset
  processed:{message_id}     -> JSON con la clasificación del mensaje,
                                 el telegram_message_id (si se envió alerta)
                                 y su estado (pending/answered/dismissed),
                                 con TTL para no acumular estado indefinido
  tg_msg:{telegram_message_id} -> gmail message_id correspondiente. Las
                                 reacciones de Telegram solo traen el
                                 message_id de Telegram, así que este
                                 índice permite encontrar de vuelta el
                                 mensaje de Gmail al que corresponden.
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


def get_processed_message(message_id: str) -> dict[str, Any] | None:
    """Devuelve el documento guardado de un mensaje procesado, o None."""
    raw = _redis_command("GET", f"processed:{message_id}")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Documento corrupto en Upstash para processed:%s; se ignora", message_id)
        return None


def mark_message_processed(
    email: dict[str, Any],
    classification: dict[str, Any],
    *,
    telegram_sent: bool,
    telegram_message_id: int | None = None,
) -> None:
    """Registra un mensaje como procesado, con su clasificación y resultado.

    Si se envió alerta, guarda también el `telegram_message_id` (para poder
    editar ese mensaje más tarde) y el estado "pending", a la espera de que
    el usuario pulse "Marcar como respondido".
    """
    doc = {
        "message_id": email.get("message_id", ""),
        "thread_id": email.get("thread_id", ""),
        "sender": email.get("sender", ""),
        "subject": email.get("subject", ""),
        "snippet": email.get("snippet", ""),
        "received_at": email.get("date", ""),
        "score": classification.get("score", 0),
        "reason": classification.get("reason", ""),
        "category": classification.get("category", ""),
        "requires_action": classification.get("requires_action", False),
        "urgency": classification.get("urgency", "low"),
        "telegram_sent": telegram_sent,
        "telegram_message_id": telegram_message_id,
        "status": "pending" if telegram_sent else "n/a",
    }
    message_id = email.get("message_id", "")
    _redis_command(
        "SET",
        f"processed:{message_id}",
        json.dumps(doc),
        "EX",
        str(config.PROCESSED_MESSAGE_TTL_SECONDS),
    )
    if telegram_message_id is not None:
        _redis_command(
            "SET",
            f"tg_msg:{telegram_message_id}",
            message_id,
            "EX",
            str(config.PROCESSED_MESSAGE_TTL_SECONDS),
        )


def get_gmail_message_id_for_telegram(telegram_message_id: int) -> str | None:
    """Traduce un `telegram_message_id` al `message_id` de Gmail que le
    corresponde, o None si no hay (mensaje no rastreado o TTL expirado)."""
    return _redis_command("GET", f"tg_msg:{telegram_message_id}")


def _set_alert_status(message_id: str, status: str) -> dict[str, Any] | None:
    """Actualiza el campo `status` de un mensaje procesado. Devuelve el
    documento actualizado, o None si no había estado guardado (p. ej. TTL
    expirado)."""
    doc = get_processed_message(message_id)
    if doc is None:
        return None
    doc["status"] = status
    _redis_command(
        "SET",
        f"processed:{message_id}",
        json.dumps(doc),
        "EX",
        str(config.PROCESSED_MESSAGE_TTL_SECONDS),
    )
    return doc


def mark_alert_answered(message_id: str) -> dict[str, Any] | None:
    """Marca un mensaje como respondido (reacción 👍 del usuario)."""
    return _set_alert_status(message_id, "answered")


def mark_alert_dismissed(message_id: str) -> dict[str, Any] | None:
    """Marca un mensaje como no importante (reacción 👎 del usuario)."""
    return _set_alert_status(message_id, "dismissed")


def get_telegram_update_offset() -> int:
    """Devuelve el offset de updates de Telegram ya procesados (0 si ninguno)."""
    state = get_state()
    return int(state.get("telegram_update_offset", 0) or 0)


def save_telegram_update_offset(offset: int) -> None:
    """Guarda el offset tras procesar updates de Telegram, para no
    reprocesar la misma reacción en el siguiente ciclo."""
    state = get_state()
    state["telegram_update_offset"] = int(offset)
    _redis_command("SET", STATE_KEY, json.dumps(state))
