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

    telegram_message_id = None
    if classification["score"] >= config.IMPORTANCE_THRESHOLD:
        telegram_message_id = telegram_service.send_alert(email, classification)
        if telegram_message_id:
            logger.info("Telegram alert sent for message %s", message_id)
        else:
            logger.error("No se pudo enviar la alerta de Telegram para %s", message_id)

    state_service.mark_message_processed(
        email,
        classification,
        telegram_sent=telegram_message_id is not None,
        telegram_message_id=telegram_message_id,
    )
    return True


_REACTION_ACTIONS = {
    "👍": ("mark_alert_answered", "respondido"),
    "👎": ("mark_alert_dismissed", "no importante"),
}


def process_telegram_reactions() -> None:
    """Revisa reacciones nativas puestas por el usuario (👍/👎) sobre alertas
    ya enviadas, desde el último offset guardado, y actualiza el estado en
    Upstash en consecuencia. No hay nada que enviar de vuelta a Telegram:
    la propia reacción del usuario ya es la confirmación visible.

    Se ejecuta de forma aislada: un fallo aquí no debe impedir que
    `poll_once()` siga revisando Gmail con normalidad.
    """
    offset = state_service.get_telegram_update_offset()
    updates = telegram_service.get_updates(offset)
    if not updates:
        return

    max_update_id = offset - 1
    for update in updates:
        max_update_id = max(max_update_id, update.get("update_id", max_update_id))

        reaction_update = update.get("message_reaction")
        if not reaction_update:
            continue

        # El propio bot pone una reacción 👀 al enviar la alerta; eso genera
        # su propio evento message_reaction, que hay que ignorar para no
        # procesarlo como si fuera una respuesta del usuario.
        reactor = reaction_update.get("user") or {}
        if reactor.get("is_bot"):
            continue

        telegram_message_id = reaction_update.get("message_id")
        new_emojis = {
            r.get("emoji")
            for r in reaction_update.get("new_reaction", []) or []
            if r.get("type") == "emoji"
        }
        action = next((a for emoji, a in _REACTION_ACTIONS.items() if emoji in new_emojis), None)
        if action is None:
            continue

        gmail_message_id = state_service.get_gmail_message_id_for_telegram(telegram_message_id)
        if not gmail_message_id:
            logger.warning(
                "Reacción sobre un mensaje de Telegram no rastreado: %s", telegram_message_id
            )
            continue

        doc = state_service.get_processed_message(gmail_message_id)
        if not doc or doc.get("status") != "pending":
            continue

        mark_fn_name, status_label = action
        getattr(state_service, mark_fn_name)(gmail_message_id)
        telegram_service.set_reaction(telegram_message_id, None)
        logger.info("Message %s marked as %s (reaction)", gmail_message_id, status_label)

    state_service.save_telegram_update_offset(max_update_id + 1)


def poll_once() -> None:
    """Revisa Gmail una vez: mensajes nuevos desde el último historyId."""
    try:
        process_telegram_reactions()
    except Exception:
        # Un fallo revisando reacciones no debe bloquear el polling de
        # Gmail, que es la función principal del sistema.
        logger.error("Fallo procesando reacciones de Telegram", exc_info=True)

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
        message_ids, latest_history_id = gmail_service.list_new_message_ids(
            service, last_history_id
        )
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

    # Avanzamos al historyId capturado ANTES de procesar (ver docstring de
    # list_new_message_ids): así ningún correo llegado durante el
    # procesamiento queda por delante del nuevo checkpoint.
    state_service.update_last_history_id(latest_history_id)


if __name__ == "__main__":
    poll_once()
