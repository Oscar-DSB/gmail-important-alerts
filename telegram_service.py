"""Envío y gestión de alertas por Telegram Bot API.

Usa Markdown; si el envío con formato falla, reintenta una vez en texto
plano. Escapa los caracteres especiales para evitar errores de parseo.

Cada alerta lleva un único botón ("Abrir en Gmail"). Al enviarla, el bot
pone una reacción 👀 ("pendiente de revisar") sobre su propio mensaje.
Marcar una alerta como respondida o no importante se hace reaccionando
tú mismo encima con 👍 o 👎 — no con botones. Como no hay servidor
escuchando en tiempo real, esas reacciones se recogen en el siguiente
ciclo del cron mediante `get_updates` (ver `main.process_telegram_reactions`).

Telegram solo admite un conjunto curado de emojis como reacción (no
cualquier emoji): 👀/🤔/👍/👎/❤/🔥 están confirmados como válidos; ✅/❌/⏳
no lo están (Telegram responde "REACTION_INVALID").
"""

from __future__ import annotations

import logging
from typing import Any

import requests

import config

logger = logging.getLogger(__name__)

_MARKDOWN_SPECIAL_CHARS = r"_*[]()~`>#+-=|{}.!"

_URGENCY_EMOJI = {
    "low": "🟢",
    "medium": "🟡",
    "high": "🟠",
    "critical": "🔴",
}

_URGENCY_LABEL_ES = {
    "low": "Baja",
    "medium": "Media",
    "high": "Alta",
    "critical": "Crítica",
}

_DIVIDER = "─" * 18  # carácter de dibujo de caja, no requiere escape en MarkdownV2


def escape_markdown(text: str) -> str:
    """Escapa caracteres especiales de MarkdownV2 de Telegram."""
    escaped = []
    for char in text or "":
        if char in _MARKDOWN_SPECIAL_CHARS:
            escaped.append("\\")
        escaped.append(char)
    return "".join(escaped)


def format_alert_message(email: dict[str, Any], classification: dict[str, Any]) -> str:
    """Construye el texto de la alerta en MarkdownV2, con formato de tarjeta:
    cabecera con score, remitente/asunto, categoría y urgencia como
    etiquetas compactas, motivo en cursiva y el fragmento del correo como
    cita nativa de Telegram.
    """
    score = classification.get("score", 0)
    urgency_key = classification.get("urgency", "low")
    emoji = _URGENCY_EMOJI.get(urgency_key, "🟡")
    urgency_label = escape_markdown(_URGENCY_LABEL_ES.get(urgency_key, urgency_key.capitalize()))

    sender = escape_markdown(email.get("sender", "Desconocido"))
    subject = escape_markdown(email.get("subject", "(sin asunto)"))
    category = escape_markdown(classification.get("category", "desconocida"))
    reason = escape_markdown(classification.get("reason", ""))
    snippet = escape_markdown((email.get("snippet") or "")[:280])

    lines = [
        f"{emoji} *CORREO IMPORTANTE — {score}/10*",
        _DIVIDER,
        f"👤 *{sender}*",
        f"📌 {subject}",
        "",
        f"🏷 {category}    ⚡ {urgency_label}",
    ]
    if reason:
        lines += ["", f"_{reason}_"]
    if snippet:
        lines += ["", f"> {snippet}"]

    return "\n".join(lines)


def _gmail_button(link: str) -> dict[str, Any] | None:
    """Teclado con el único botón "Abrir en Gmail".

    Devuelve None si no hay enlace válido (Telegram rechaza botones con
    url vacía), para no romper el envío del mensaje por un dato ausente.
    """
    if not link:
        return None
    return {"inline_keyboard": [[{"text": "📧 Abrir en Gmail", "url": link}]]}


def _post(method: str, payload: dict[str, Any]) -> requests.Response:
    token = config.get_telegram_bot_token()
    url = f"https://api.telegram.org/bot{token}/{method}"
    return requests.post(url, json=payload, timeout=config.HTTP_TIMEOUT_SECONDS)


def _post_message(
    text: str, parse_mode: str | None, reply_markup: dict[str, Any] | None
) -> requests.Response:
    payload: dict[str, Any] = {
        "chat_id": config.get_telegram_chat_id(),
        "text": text,
        "disable_web_page_preview": True,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return _post("sendMessage", payload)


def set_reaction(telegram_message_id: int, emoji: str | None) -> bool:
    """Pone una reacción emoji sobre el mensaje, o la retira si `emoji` es
    None (Telegram limpia la reacción del bot con `reaction: []`)."""
    payload: dict[str, Any] = {
        "chat_id": config.get_telegram_chat_id(),
        "message_id": telegram_message_id,
        "reaction": [{"type": "emoji", "emoji": emoji}] if emoji else [],
    }
    try:
        response = _post("setMessageReaction", payload)
        if response.status_code == 200:
            return True
        logger.warning(
            "Telegram respondió %d al poner/quitar la reacción del mensaje %d",
            response.status_code,
            telegram_message_id,
        )
        return False
    except requests.RequestException:
        logger.warning(
            "Fallo de red poniendo/quitando reacción en mensaje %d", telegram_message_id, exc_info=True
        )
        return False


def send_alert(email: dict[str, Any], classification: dict[str, Any]) -> int | None:
    """Envía la alerta a Telegram. Devuelve el `message_id` de Telegram si se
    envió correctamente, o None si falló.

    Si el envío con MarkdownV2 falla, reintenta una vez con texto plano sin
    formato para maximizar la probabilidad de entrega. El botón "Abrir en
    Gmail" se incluye en ambos intentos. Tras un envío correcto, se pone la
    reacción 👀 como indicador de "pendiente de revisar" (best-effort: si
    falla, no se considera un fallo del envío).
    """
    button = _gmail_button(email.get("gmail_link", ""))
    formatted = format_alert_message(email, classification)
    message_id: int | None = None
    try:
        response = _post_message(formatted, parse_mode="MarkdownV2", reply_markup=button)
        if response.status_code == 200:
            message_id = response.json()["result"]["message_id"]
        else:
            logger.warning(
                "Telegram respondió %d al enviar con Markdown; reintentando en texto plano",
                response.status_code,
            )
    except requests.RequestException:
        logger.warning("Fallo de red enviando alerta con Markdown a Telegram", exc_info=True)

    if message_id is None:
        urgency_key = classification.get("urgency", "low")
        emoji = _URGENCY_EMOJI.get(urgency_key, "🟡")
        urgency_label = _URGENCY_LABEL_ES.get(urgency_key, urgency_key.capitalize())
        plain_lines = [
            f"{emoji} CORREO IMPORTANTE — {classification.get('score', 0)}/10",
            _DIVIDER,
            f"👤 {email.get('sender', 'Desconocido')}",
            f"📌 {email.get('subject', '(sin asunto)')}",
            "",
            f"🏷 {classification.get('category', 'desconocida')}    ⚡ {urgency_label}",
        ]
        reason = classification.get("reason", "")
        if reason:
            plain_lines += ["", reason]
        snippet = (email.get("snippet") or "")[:280]
        if snippet:
            plain_lines += ["", f"“{snippet}”"]
        plain_text = "\n".join(plain_lines)
        try:
            response = _post_message(plain_text, parse_mode=None, reply_markup=button)
            if response.status_code == 200:
                message_id = response.json()["result"]["message_id"]
            else:
                logger.error("Telegram respondió %d al enviar en texto plano", response.status_code)
                return None
        except requests.RequestException:
            logger.error("Fallo de red enviando alerta en texto plano a Telegram", exc_info=True)
            return None

    set_reaction(message_id, "👀")
    return message_id


def get_updates(offset: int) -> list[dict[str, Any]]:
    """Recupera actualizaciones de Telegram desde `offset`, incluyendo
    explícitamente `message_reaction` (Telegram no las envía por defecto
    sin pedirlo). `timeout=0` para respuesta inmediata (no long-polling):
    esto se ejecuta dentro de un cron, no de un proceso persistente.

    Se usa POST con body JSON (no GET con query params) porque
    `allowed_updates` es un array y la codificación de listas en query
    string no coincide con el formato JSON que espera Telegram.
    """
    payload = {
        "offset": offset,
        "timeout": 0,
        "allowed_updates": ["message_reaction"],
    }
    response = _post("getUpdates", payload)
    response.raise_for_status()
    return response.json().get("result", [])
