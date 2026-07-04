"""Clasificación de importancia de correos con Gemini.

Usa el SDK oficial `google-genai`. La respuesta del modelo nunca se confía
directamente: se limpia de bloques Markdown, se valida como JSON y se
normalizan todos los campos con valores seguros por defecto.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import config

logger = logging.getLogger(__name__)

VALID_URGENCIES: frozenset[str] = frozenset({"low", "medium", "high", "critical"})

_SAFE_DEFAULT: dict[str, Any] = {
    "score": 0,
    "reason": "Sin clasificación",
    "category": "desconocida",
    "requires_action": False,
    "urgency": "low",
}

_SYSTEM_INSTRUCTIONS = """Eres un sistema que clasifica la importancia de correos personales.
Evalúa si el usuario necesita conocer o atender este correo pronto.
Criterios de importancia:
- Solicitudes directas al usuario.
- Fechas límite.
- Reuniones, entrevistas o citas.
- Universidad, profesores y prácticas.
- Trabajo, oportunidades laborales y documentación.
- Problemas de seguridad o acceso.
- Pagos, facturas o incidencias económicas.
- Mensajes personales que necesitan respuesta.
- Cambios importantes en servicios utilizados por el usuario.
Criterios de poca importancia:
- Publicidad.
- Newsletters.
- Promociones.
- Resúmenes automáticos.
- Contenido informativo sin acción necesaria.
- Notificaciones repetitivas.
- Correos masivos.
Devuelve exclusivamente JSON válido con esta estructura:
{"score": 0, "reason": "Explicación breve", "category": "categoria", "requires_action": false, "urgency": "low"}
Reglas:
- score debe ser un número entero entre 0 y 10.
- reason debe ser breve y clara.
- category debe ser una categoría corta.
- requires_action debe ser true o false.
- urgency solo puede ser low, medium, high o critical.
- No incluyas texto fuera del JSON."""


def build_prompt(email: dict[str, Any]) -> str:
    """Construye el prompt para el modelo con el cuerpo truncado."""
    body = (email.get("body_text") or email.get("snippet") or "")[: config.MAX_EMAIL_CHARACTERS]
    return (
        f"{_SYSTEM_INSTRUCTIONS}\n\n"
        "Contenido del correo:\n"
        f"Remitente: {email.get('sender', '')}\n"
        f"Asunto: {email.get('subject', '')}\n"
        f"Fecha: {email.get('date', '')}\n"
        f"Snippet: {email.get('snippet', '')}\n"
        f"Contenido: {body}\n"
    )


def _strip_markdown_fences(text: str) -> str:
    """Elimina vallas Markdown tipo ```json ... ``` que rodean el JSON."""
    cleaned = text.strip()
    fence = re.match(r"^```[a-zA-Z]*\s*(.*?)\s*```$", cleaned, re.DOTALL)
    if fence:
        return fence.group(1).strip()
    return cleaned


def _extract_json_object(text: str) -> str:
    """Extrae el primer objeto JSON balanceado del texto."""
    start = text.find("{")
    if start == -1:
        return text
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return text[start:]


def validate_response(raw_text: str) -> dict[str, Any]:
    """Valida y normaliza la respuesta cruda del modelo.

    Lanza ValueError si no se puede extraer JSON parseable. Los campos
    individuales inválidos se sustituyen por valores seguros.
    """
    if not raw_text or not raw_text.strip():
        raise ValueError("Respuesta vacía del modelo")

    candidate = _extract_json_object(_strip_markdown_fences(raw_text))
    try:
        data = json.loads(candidate)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("La respuesta del modelo no es JSON válido") from exc

    if not isinstance(data, dict):
        raise ValueError("La respuesta del modelo no es un objeto JSON")

    result = dict(_SAFE_DEFAULT)

    # score: entero 0-10.
    try:
        score = int(data.get("score", 0))
    except (TypeError, ValueError):
        score = 0
    result["score"] = max(0, min(10, score))

    reason = data.get("reason")
    if isinstance(reason, str) and reason.strip():
        result["reason"] = reason.strip()

    category = data.get("category")
    if isinstance(category, str) and category.strip():
        result["category"] = category.strip()

    result["requires_action"] = bool(data.get("requires_action", False))

    urgency = data.get("urgency")
    if isinstance(urgency, str) and urgency.lower() in VALID_URGENCIES:
        result["urgency"] = urgency.lower()
    else:
        result["urgency"] = "low"

    return result


def _generate_content(prompt: str) -> str:
    """Llama a Gemini y devuelve el texto de la respuesta."""
    from google import genai  # import perezoso

    client = genai.Client(api_key=config.get_gemini_api_key())
    response = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=prompt,
    )
    return getattr(response, "text", "") or ""


def classify_email(email: dict[str, Any]) -> dict[str, Any]:
    """Clasifica un correo con Gemini y devuelve el resultado validado.

    Propaga la excepción si la llamada al modelo falla, para que el correo
    NO se marque como notificado y se reintente en el siguiente polling.
    """
    prompt = build_prompt(email)
    raw_text = _generate_content(prompt)
    result = validate_response(raw_text)
    logger.info(
        "Message %s classified with score %d",
        email.get("message_id", "?"),
        result["score"],
    )
    return result
