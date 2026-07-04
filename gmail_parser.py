"""Parser de mensajes MIME de Gmail API.

Extrae los campos relevantes de un mensaje devuelto por
`users().messages().get(format="full")` y obtiene un cuerpo de texto limpio,
priorizando text/plain y recurriendo a HTML→texto con BeautifulSoup.
"""

from __future__ import annotations

import base64
import html as html_lib
import logging
from typing import Any

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def _decode_base64url(data: str) -> str:
    """Decodifica contenido Base64 URL-safe, tolerando padding ausente."""
    if not data:
        return ""
    padding = "=" * (-len(data) % 4)
    try:
        raw = base64.urlsafe_b64decode(data + padding)
    except (ValueError, base64.binascii.Error):  # type: ignore[attr-defined]
        logger.warning("No se pudo decodificar una parte Base64 del mensaje")
        return ""
    return raw.decode("utf-8", errors="replace")


def _collect_parts(payload: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Recorre recursivamente el árbol MIME y recolecta textos plano y HTML."""
    plains: list[str] = []
    htmls: list[str] = []

    mime_type = payload.get("mimeType", "") or ""
    body = payload.get("body", {}) or {}
    data = body.get("data")

    if data:
        if mime_type == "text/plain":
            plains.append(_decode_base64url(data))
        elif mime_type == "text/html":
            htmls.append(_decode_base64url(data))

    for part in payload.get("parts", []) or []:
        child_plains, child_htmls = _collect_parts(part)
        plains.extend(child_plains)
        htmls.extend(child_htmls)

    return plains, htmls


def html_to_text(html: str) -> str:
    """Convierte HTML a texto plano legible, eliminando scripts y estilos."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "head", "title", "meta"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _extract_headers(payload: dict[str, Any]) -> dict[str, str]:
    """Devuelve las cabeceras en un dict con claves en minúscula."""
    headers: dict[str, str] = {}
    for header in payload.get("headers", []) or []:
        name = (header.get("name") or "").lower()
        if name:
            headers[name] = header.get("value", "") or ""
    return headers


def extract_body_text(payload: dict[str, Any]) -> str:
    """Obtiene el mejor cuerpo textual disponible del payload MIME."""
    plains, htmls = _collect_parts(payload)
    plain_text = "\n".join(p for p in plains if p).strip()
    if plain_text:
        return plain_text
    html_joined = "\n".join(h for h in htmls if h)
    return html_to_text(html_joined).strip()


def build_gmail_link(message_id: str) -> str:
    """Construye un enlace directo para abrir el correo en Gmail."""
    return f"https://mail.google.com/mail/u/0/#inbox/{message_id}"


def parse_message(message: dict[str, Any]) -> dict[str, Any]:
    """Convierte un mensaje de Gmail API en un dict con los campos relevantes.

    Es tolerante a cabeceras y cuerpos ausentes: cualquier campo faltante se
    devuelve como cadena vacía o lista vacía.
    """
    payload = message.get("payload", {}) or {}
    headers = _extract_headers(payload)

    message_id = message.get("id", "")

    return {
        "message_id": message_id,
        "thread_id": message.get("threadId", ""),
        # Gmail devuelve a veces "from"/"subject"/"snippet" con entidades HTML
        # sin decodificar (p. ej. &quot; en vez de "), incluso para mensajes
        # sin relación con HTML. Se decodifican aquí para mostrar texto limpio
        # tanto en Telegram como en el prompt enviado a Gemini.
        "sender": html_lib.unescape(headers.get("from", "")),
        "recipient": html_lib.unescape(headers.get("to", "")),
        "subject": html_lib.unescape(headers.get("subject", "")),
        "date": headers.get("date", ""),
        "labels": list(message.get("labelIds", []) or []),
        "snippet": html_lib.unescape(message.get("snippet", "") or ""),
        "body_text": extract_body_text(payload),
        "gmail_link": build_gmail_link(message_id),
    }
