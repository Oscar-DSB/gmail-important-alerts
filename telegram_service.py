"""Envío de alertas por Telegram Bot API.

Usa Markdown; si el envío con formato falla, reintenta una vez en texto
plano. Escapa los caracteres especiales para evitar errores de parseo.
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


def escape_markdown(text: str) -> str:
    """Escapa caracteres especiales de MarkdownV2 de Telegram."""
    escaped = []
    for char in text or "":
        if char in _MARKDOWN_SPECIAL_CHARS:
            escaped.append("\\")
        escaped.append(char)
    return "".join(escaped)


def format_alert_message(email: dict[str, Any], classification: dict[str, Any]) -> str:
    """Construye el texto de la alerta en MarkdownV2."""
    score = classification.get("score", 0)
    emoji = _URGENCY_EMOJI.get(classification.get("urgency", "low"), "🟡")

    sender = escape_markdown(email.get("sender", "Desconocido"))
    subject = escape_markdown(email.get("subject", "(sin asunto)"))
    category = escape_markdown(classification.get("category", "desconocida"))
    urgency = escape_markdown(classification.get("urgency", "low"))
    reason = escape_markdown(classification.get("reason", ""))
    snippet = escape_markdown((email.get("snippet") or "")[:300])
    link = email.get("gmail_link", "")

    return (
        f"{emoji} *CORREO IMPORTANTE — {score}/10*\n"
        f"*De:* {sender}\n"
        f"*Asunto:* {subject}\n"
        f"*Categoría:* {category}\n"
        f"*Urgencia:* {urgency}\n"
        f"*Motivo:*\n{reason}\n"
        f"*Resumen:*\n{snippet}\n\n"
        f"[Abrir en Gmail]({escape_markdown(link)})"
    )


def _post_message(text: str, parse_mode: str | None) -> requests.Response:
    token = config.get_telegram_bot_token()
    chat_id = config.get_telegram_chat_id()
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    return requests.post(url, json=payload, timeout=config.HTTP_TIMEOUT_SECONDS)


def send_alert(email: dict[str, Any], classification: dict[str, Any]) -> bool:
    """Envía la alerta a Telegram. Devuelve True si se envió correctamente.

    Si el envío con MarkdownV2 falla, reintenta una vez con texto plano sin
    formato para maximizar la probabilidad de entrega.
    """
    formatted = format_alert_message(email, classification)
    try:
        response = _post_message(formatted, parse_mode="MarkdownV2")
        if response.status_code == 200:
            return True
        logger.warning(
            "Telegram respondió %d al enviar con Markdown; reintentando en texto plano",
            response.status_code,
        )
    except requests.RequestException:
        logger.warning("Fallo de red enviando alerta con Markdown a Telegram", exc_info=True)

    plain_text = (
        f"CORREO IMPORTANTE — {classification.get('score', 0)}/10\n"
        f"De: {email.get('sender', 'Desconocido')}\n"
        f"Asunto: {email.get('subject', '(sin asunto)')}\n"
        f"Categoría: {classification.get('category', 'desconocida')}\n"
        f"Urgencia: {classification.get('urgency', 'low')}\n"
        f"Motivo: {classification.get('reason', '')}\n"
        f"Resumen: {(email.get('snippet') or '')[:300]}\n"
        f"Abrir en Gmail: {email.get('gmail_link', '')}"
    )
    try:
        response = _post_message(plain_text, parse_mode=None)
        if response.status_code == 200:
            return True
        logger.error("Telegram respondió %d al enviar en texto plano", response.status_code)
        return False
    except requests.RequestException:
        logger.error("Fallo de red enviando alerta en texto plano a Telegram", exc_info=True)
        return False
