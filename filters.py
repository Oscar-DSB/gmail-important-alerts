"""Filtros locales previos a la clasificación con Gemini.

Descartan correos claramente promocionales o masivos sin gastar una llamada
al modelo. Un correo con términos potencialmente importantes nunca se descarta
automáticamente, aunque proceda de una dirección `noreply`.
"""

from __future__ import annotations

from typing import Any

# Palabras orientativas de correo descartable (baja importancia).
DISCARD_KEYWORDS: tuple[str, ...] = (
    "newsletter",
    "unsubscribe",
    "cancelar suscripcion",
    "cancelar suscripción",
    "darse de baja",
    "promocion",
    "promoción",
    "oferta",
    "descuento",
    "publicidad",
    "resumen semanal",
    "weekly digest",
    "marketing",
    "sale",
    "black friday",
    "cyber monday",
    "rebajas",
)

# Términos que impiden el descarte automático (posible correo importante).
# No otorgan puntuación alta: solo evitan que el filtro lo descarte.
IMPORTANT_KEYWORDS: tuple[str, ...] = (
    "urgente",
    "entrevista",
    "practicas",
    "prácticas",
    "universidad",
    "profesor",
    "examen",
    "confirmacion",
    "confirmación",
    "fecha limite",
    "fecha límite",
    "deadline",
    "reunion",
    "reunión",
    "incidencia",
    "seguridad",
    "contrasena",
    "contraseña",
    "password",
    "pago",
    "factura",
    "documentacion",
    "documentación",
    "oferta laboral",
    "admision",
    "admisión",
    "beca",
)

# Etiquetas de Gmail que indican correo de baja prioridad.
DISCARD_LABELS: frozenset[str] = frozenset(
    {"CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL", "SPAM"}
)


def _normalize(text: str) -> str:
    return (text or "").lower()


def has_important_signal(email: dict[str, Any]) -> bool:
    """True si el correo contiene términos que impiden el descarte."""
    haystack = _normalize(
        f"{email.get('subject', '')} {email.get('snippet', '')} {email.get('body_text', '')}"
    )
    return any(keyword in haystack for keyword in IMPORTANT_KEYWORDS)


def should_discard(email: dict[str, Any]) -> tuple[bool, str]:
    """Decide si el correo puede descartarse sin llamar a Gemini.

    Devuelve (descartar, motivo). Si `descartar` es True, se asigna una
    puntuación baja sin consultar al modelo.
    """
    # Los términos importantes tienen prioridad: nunca se descarta.
    if has_important_signal(email):
        return False, "Contiene términos potencialmente importantes"

    labels = set(email.get("labels", []) or [])
    matched_labels = labels & DISCARD_LABELS
    if matched_labels:
        return True, f"Etiqueta de baja prioridad: {', '.join(sorted(matched_labels))}"

    haystack = _normalize(
        f"{email.get('subject', '')} {email.get('snippet', '')} {email.get('body_text', '')}"
    )
    for keyword in DISCARD_KEYWORDS:
        if keyword in haystack:
            return True, f"Contenido promocional detectado: '{keyword}'"

    return False, "Sin señales de descarte; requiere análisis"
