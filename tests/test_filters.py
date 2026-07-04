from filters import should_discard


def _email(**overrides):
    base = {
        "sender": "someone@example.com",
        "subject": "",
        "snippet": "",
        "body_text": "",
        "labels": [],
    }
    base.update(overrides)
    return base


def test_newsletter_is_discarded():
    email = _email(subject="Nuestra newsletter semanal", snippet="Novedades del mes")
    discard, _ = should_discard(email)
    assert discard is True


def test_advertising_is_discarded():
    email = _email(subject="¡Oferta especial solo hoy!", snippet="Gran descuento en publicidad")
    discard, _ = should_discard(email)
    assert discard is True


def test_professor_email_is_not_discarded():
    email = _email(
        sender="profesor@universidad.edu",
        subject="Recordatorio de examen",
        snippet="El examen final es la próxima semana",
    )
    discard, _ = should_discard(email)
    assert discard is False


def test_interview_email_is_not_discarded():
    email = _email(
        subject="Confirmación de entrevista",
        snippet="Nos gustaría confirmar tu entrevista para el puesto",
    )
    discard, _ = should_discard(email)
    assert discard is False


def test_noreply_important_email_is_not_discarded():
    email = _email(
        sender="noreply@universidad.edu",
        subject="Confirmación de admisión",
        snippet="Tu solicitud de beca ha sido aprobada",
    )
    discard, _ = should_discard(email)
    assert discard is False


def test_promotional_with_unsubscribe_is_discarded():
    email = _email(
        subject="No te pierdas nuestras rebajas",
        snippet="Haz clic aquí para unsubscribe en cualquier momento",
    )
    discard, _ = should_discard(email)
    assert discard is True


def test_discard_label_promotions():
    email = _email(subject="Aviso", snippet="Aviso general", labels=["CATEGORY_PROMOTIONS"])
    discard, _ = should_discard(email)
    assert discard is True
