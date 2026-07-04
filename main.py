"""Punto de entrada del polling programado (GitHub Actions).

`poll_once()` se ejecuta periódicamente (cron de GitHub Actions). No hay
`watch()` de Gmail: cada ejecución consulta `users.history.list` desde el
último `historyId` guardado. Idempotente: reprocesar la misma ventana de
historial no duplica alertas.
"""

from __future__ import annotations

import logging

import config
import filters
import gmail_service
import importance_classifier
import state_service
import telegram_service
from gmail_parser import parse_message

config.configure_logging()
logger = logging.getLogger(__name__)


def _process_single_message(service, message_id: str) -> bool:
    """Procesa un mensaje: idempotencia, filtros, clasificación y alerta.

    Devuelve False si el mensaje NO quedó marcado como procesado (p. ej. fallo
    de Gemini), para que el llamador sepa que no debe avanzar el historyId
    todavía y se reintente en la próxima ejecución del polling.
    """
    if state_service.is_message_processed(message_id):
        logger.info("Message %s already processed, skipping", message_id)
        return True

    logger.info("Processing message %s", message_id)
    raw_message = gmail_service.get_message(service, message_id)
    if raw_message is None:
        # Mensaje eliminado antes de poder recuperarlo: nada que procesar.
        return True

    email = parse_message(raw_message)

    discard, reason = filters.should_discard(email)
    if discard:
        logger.info("Message %s discarded by local filter: %s", message_id, reason)
        classification = {
            "score": 0,
            "reason": reason,
            "category": "descartado",
            "requires_action": False,
            "urgency": "low",
        }
        state_service.mark_message_processed(email, classification, telegram_sent=False)
        return True

    try:
        classification = importance_classifier.classify_email(email)
    except Exception:
        # No se marca como procesado: el historyId no avanzará y la
        # siguiente ejecución del polling reintentará este mensaje.
        logger.error("Fallo clasificando mensaje %s con Gemini", message_id, exc_info=True)
        return False

    telegram_sent = False
    if classification["score"] >= config.IMPORTANCE_THRESHOLD:
        telegram_sent = telegram_service.send_alert(email, classification)
        if telegram_sent:
            logger.info("Telegram alert sent for message %s", message_id)
        else:
            logger.error("No se pudo enviar la alerta de Telegram para %s", message_id)

    state_service.mark_message_processed(email, classification, telegram_sent=telegram_sent)
    return True


def poll_once() -> None:
    """Revisa Gmail una vez: mensajes nuevos desde el último historyId."""
    logger.info("Polling Gmail for new messages")

    service = gmail_service.build_gmail_client()
    last_history_id = state_service.get_last_history_id()

    if last_history_id is None:
        # Primera ejecución sin estado previo: fijamos el historyId actual
        # como línea base, sin procesar la bandeja histórica.
        profile = gmail_service.get_profile(service)
        baseline_history_id = str(profile.get("historyId", ""))
        logger.info("No previous state found; baselining at historyId %s", baseline_history_id)
        state_service.update_last_history_id(baseline_history_id)
        return

    try:
        message_ids = gmail_service.list_new_message_ids(service, last_history_id)
    except gmail_service.HistoryIdTooOldError:
        logger.error(
            "historyId %s demasiado antiguo; reinicializando estado de forma segura",
            last_history_id,
        )
        profile = gmail_service.get_profile(service)
        current_history_id = str(profile.get("historyId", ""))
        state_service.update_last_history_id(current_history_id)
        return

    logger.info("Found %d new message IDs", len(message_ids))

    all_succeeded = True
    for message_id in message_ids:
        if not _process_single_message(service, message_id):
            all_succeeded = False

    if not all_succeeded:
        # No avanzamos el historyId: en la próxima ejecución, los mensajes
        # ya marcados como procesados se saltarán (idempotencia) y solo se
        # reintentarán los que fallaron.
        logger.error(
            "Uno o más mensajes no se procesaron correctamente; historyId no avanzado"
        )
        return

    # Solo avanzamos el historyId tras procesar todos los mensajes con éxito.
    profile = gmail_service.get_profile(service)
    current_history_id = str(profile.get("historyId", ""))
    state_service.update_last_history_id(current_history_id)


if __name__ == "__main__":
    poll_once()
