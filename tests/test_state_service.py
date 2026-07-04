import json

import state_service


class _FakeResponse:
    def __init__(self, result):
        self._result = result

    def raise_for_status(self):
        return None

    def json(self):
        return {"result": self._result}


def test_get_last_history_id_none_when_no_state(monkeypatch):
    monkeypatch.setattr(state_service, "_redis_command", lambda *args: None)
    assert state_service.get_last_history_id() is None


def test_get_last_history_id_returns_stored_value(monkeypatch):
    stored = json.dumps({"last_history_id": "12345"})
    monkeypatch.setattr(state_service, "_redis_command", lambda *args: stored)
    assert state_service.get_last_history_id() == "12345"


def test_update_last_history_id_sends_set_command(monkeypatch):
    calls = []

    def fake_command(*args):
        calls.append(args)
        if args[0] == "GET":
            return None
        return "OK"

    monkeypatch.setattr(state_service, "_redis_command", fake_command)
    state_service.update_last_history_id("999")

    assert calls[0] == ("GET", state_service.STATE_KEY)
    assert calls[1][0] == "SET"
    assert calls[1][1] == state_service.STATE_KEY
    payload = json.loads(calls[1][2])
    assert payload["last_history_id"] == "999"


def test_update_last_history_id_preserves_existing_fields(monkeypatch):
    existing = json.dumps({"last_history_id": "1", "extra_field": "kept"})

    def fake_command(*args):
        if args[0] == "GET":
            return existing
        return "OK"

    calls = []

    def spy(*args):
        calls.append(args)
        return fake_command(*args)

    monkeypatch.setattr(state_service, "_redis_command", spy)
    state_service.update_last_history_id("2")

    set_call = next(c for c in calls if c[0] == "SET")
    payload = json.loads(set_call[2])
    assert payload["last_history_id"] == "2"
    assert payload["extra_field"] == "kept"


def test_is_message_processed_true(monkeypatch):
    monkeypatch.setattr(state_service, "_redis_command", lambda *args: 1)
    assert state_service.is_message_processed("abc123") is True


def test_is_message_processed_false(monkeypatch):
    monkeypatch.setattr(state_service, "_redis_command", lambda *args: 0)
    assert state_service.is_message_processed("abc123") is False


def test_mark_message_processed_sends_expiring_set(monkeypatch):
    calls = []

    def fake_command(*args):
        calls.append(args)
        return "OK"

    monkeypatch.setattr(state_service, "_redis_command", fake_command)

    email = {"message_id": "msg1", "thread_id": "t1", "sender": "a@b.com", "subject": "Hola"}
    classification = {"score": 8, "reason": "x", "category": "y", "requires_action": True, "urgency": "high"}

    state_service.mark_message_processed(email, classification, telegram_sent=True)

    assert len(calls) == 1
    command, key, value, ex_flag, ttl = calls[0]
    assert command == "SET"
    assert key == "processed:msg1"
    assert ex_flag == "EX"
    assert ttl == str(state_service.config.PROCESSED_MESSAGE_TTL_SECONDS)
    payload = json.loads(value)
    assert payload["message_id"] == "msg1"
    assert payload["score"] == 8
    assert payload["telegram_sent"] is True


def test_get_state_handles_corrupt_json(monkeypatch):
    monkeypatch.setattr(state_service, "_redis_command", lambda *args: "not-json{")
    assert state_service.get_state() == {}
