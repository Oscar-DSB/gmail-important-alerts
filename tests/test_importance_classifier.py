import pytest

import importance_classifier as ic


def test_validate_response_valid_json():
    raw = '{"score": 8, "reason": "Entrevista pendiente", "category": "entrevista", "requires_action": true, "urgency": "high"}'
    result = ic.validate_response(raw)
    assert result == {
        "score": 8,
        "reason": "Entrevista pendiente",
        "category": "entrevista",
        "requires_action": True,
        "urgency": "high",
    }


def test_validate_response_json_in_markdown_block():
    raw = '```json\n{"score": 5, "reason": "Ok", "category": "general", "requires_action": false, "urgency": "medium"}\n```'
    result = ic.validate_response(raw)
    assert result["score"] == 5
    assert result["urgency"] == "medium"


def test_validate_response_score_out_of_range_clamped():
    raw = '{"score": 42, "reason": "Fuera de rango", "category": "x", "requires_action": false, "urgency": "low"}'
    result = ic.validate_response(raw)
    assert result["score"] == 10

    raw_negative = '{"score": -5, "reason": "Negativo", "category": "x", "requires_action": false, "urgency": "low"}'
    result_negative = ic.validate_response(raw_negative)
    assert result_negative["score"] == 0


def test_validate_response_missing_fields_uses_defaults():
    raw = '{"score": 3}'
    result = ic.validate_response(raw)
    assert result["score"] == 3
    assert result["reason"] == "Sin clasificación"
    assert result["category"] == "desconocida"
    assert result["requires_action"] is False
    assert result["urgency"] == "low"


def test_validate_response_invalid_json_raises():
    with pytest.raises(ValueError):
        ic.validate_response("esto no es json en absoluto")


def test_validate_response_empty_raises():
    with pytest.raises(ValueError):
        ic.validate_response("")


def test_validate_response_unknown_urgency_defaults_to_low():
    raw = '{"score": 6, "reason": "x", "category": "x", "requires_action": false, "urgency": "catastrofico"}'
    result = ic.validate_response(raw)
    assert result["urgency"] == "low"


def test_classify_email_uses_mocked_gemini(monkeypatch):
    monkeypatch.setattr(
        ic,
        "_generate_content",
        lambda prompt: '{"score": 9, "reason": "Urgente", "category": "trabajo", "requires_action": true, "urgency": "critical"}',
    )
    email = {
        "message_id": "abc",
        "sender": "jefe@empresa.com",
        "subject": "Reunión urgente",
        "date": "hoy",
        "snippet": "necesito verte",
        "body_text": "necesito verte hoy",
    }
    result = ic.classify_email(email)
    assert result["score"] == 9
    assert result["urgency"] == "critical"


def test_classify_email_propagates_failure(monkeypatch):
    def _raise(prompt):
        raise RuntimeError("Gemini no disponible")

    monkeypatch.setattr(ic, "_generate_content", _raise)
    email = {"message_id": "abc", "subject": "x", "snippet": "x", "body_text": "x"}

    with pytest.raises(RuntimeError):
        ic.classify_email(email)
