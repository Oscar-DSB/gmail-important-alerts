"""Acceso a Gmail API: credenciales OAuth, history.list y mensajes.

Sincronización por polling: no requiere ningún `watch()` activo, solo el
`historyId` guardado en el estado. Gestiona: token expirado, refresh token
inválido, historyId demasiado antiguo (404), mensaje eliminado antes de
recuperarlo, errores 401/403/404/429/500 y paginación en
users.history.list.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import config

logger = logging.getLogger(__name__)


class HistoryIdTooOldError(Exception):
    """Se lanza cuando Gmail rechaza el historyId por ser demasiado antiguo."""


def _load_credentials():
    """Carga credenciales OAuth 2.0 desde el JSON almacenado en Secret Manager."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    token_json = config.get_gmail_token_json()
    data = json.loads(token_json)
    credentials = Credentials.from_authorized_user_info(data, config.GMAIL_SCOPES)

    if not credentials.valid:
        if credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            raise RuntimeError(
                "Credenciales de Gmail inválidas y sin refresh_token disponible"
            )

    return credentials


def build_gmail_client():
    """Construye el cliente de Gmail API autenticado."""
    from googleapiclient.discovery import build

    credentials = _load_credentials()
    return build("gmail", "v1", credentials=credentials, cache_discovery=False)


def get_profile(service: Any) -> dict[str, Any]:
    """Devuelve el perfil de Gmail (incluye historyId actual)."""
    return service.users().getProfile(userId="me").execute()


def list_new_message_ids(service: Any, start_history_id: str) -> tuple[list[str], str]:
    """Recupera IDs de mensajes nuevos desde `start_history_id`, paginando.

    Elimina duplicados manteniendo el orden. Lanza HistoryIdTooOldError si
    Gmail responde 404 porque el historyId ya no es válido.

    Devuelve también el `historyId` que Gmail reporta como "actual" en el
    momento exacto de esta llamada (antes de procesar ningún mensaje), para
    que el llamador pueda usarlo como nuevo checkpoint sin dejar una ventana
    de carrera: si se pidiera un historyId "actual" después de procesar los
    mensajes, un correo llegado durante el procesamiento quedaría por
    delante del nuevo checkpoint y jamás se recuperaría.
    """
    from googleapiclient.errors import HttpError

    message_ids: list[str] = []
    seen: set[str] = set()
    page_token: str | None = None
    latest_history_id = start_history_id

    while True:
        request_kwargs: dict[str, Any] = {
            "userId": "me",
            "startHistoryId": start_history_id,
            "historyTypes": ["messageAdded"],
        }
        if page_token:
            request_kwargs["pageToken"] = page_token

        try:
            response = service.users().history().list(**request_kwargs).execute()
        except HttpError as exc:
            status = getattr(exc.resp, "status", None)
            if status == 404:
                raise HistoryIdTooOldError(
                    f"historyId {start_history_id} demasiado antiguo"
                ) from exc
            if status in (401, 403, 429, 500, 503):
                logger.error("Error %s consultando Gmail history.list", status)
                raise
            raise

        for history_record in response.get("history", []) or []:
            for added in history_record.get("messagesAdded", []) or []:
                msg = added.get("message", {}) or {}
                msg_id = msg.get("id")
                if msg_id and msg_id not in seen:
                    seen.add(msg_id)
                    message_ids.append(msg_id)

        if response.get("historyId"):
            latest_history_id = str(response["historyId"])

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return message_ids, latest_history_id


def get_message(service: Any, message_id: str) -> dict[str, Any] | None:
    """Recupera un mensaje completo. Devuelve None si fue eliminado (404)."""
    from googleapiclient.errors import HttpError

    try:
        return (
            service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )
    except HttpError as exc:
        status = getattr(exc.resp, "status", None)
        if status == 404:
            logger.warning("Mensaje %s no encontrado (eliminado antes de recuperarlo)", message_id)
            return None
        logger.error("Error %s recuperando mensaje %s", status, message_id)
        raise
