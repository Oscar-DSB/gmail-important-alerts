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


def test_mark_message_processed_stores_telegram_message_id_and_pending_status(monkeypatch):
    calls = []

    def fake_command(*args):
        calls.append(args)
        return "OK"

    monkeypatch.setattr(state_service, "_redis_command", fake_command)

    email = {"message_id": "msg1", "sender": "a@b.com", "subject": "Hola", "snippet": "resumen"}
    classification = {"score": 9, "reason": "x", "category": "y", "urgency": "critical"}

    state_service.mark_message_processed(
        email, classification, telegram_sent=True, telegram_message_id=777
    )

    payload = json.loads(calls[0][2])
    assert payload["telegram_message_id"] == 777
    assert payload["status"] == "pending"
    assert payload["snippet"] == "resumen"

    index_call = next(c for c in calls if c[1] == "tg_msg:777")
    assert index_call[0] == "SET"
    assert index_call[2] == "msg1"


def test_mark_message_processed_skips_index_when_not_sent(monkeypatch):
    calls = []
    monkeypatch.setattr(state_service, "_redis_command", lambda *args: calls.append(args) or "OK")

    email = {"message_id": "msg9"}
    state_service.mark_message_processed(email, {"score": 1}, telegram_sent=False)

    assert not any(c[1].startswith("tg_msg:") for c in calls if len(c) > 1)


def test_get_gmail_message_id_for_telegram(monkeypatch):
    monkeypatch.setattr(state_service, "_redis_command", lambda *args: "msg1")
    assert state_service.get_gmail_message_id_for_telegram(777) == "msg1"


def test_get_gmail_message_id_for_telegram_none_when_missing(monkeypatch):
    monkeypatch.setattr(state_service, "_redis_command", lambda *args: None)
    assert state_service.get_gmail_message_id_for_telegram(999) is None


def test_mark_message_processed_status_na_when_not_sent(monkeypatch):
    calls = []
    monkeypatch.setattr(state_service, "_redis_command", lambda *args: calls.append(args) or "OK")

    email = {"message_id": "msg2"}
    classification = {"score": 2}
    state_service.mark_message_processed(email, classification, telegram_sent=False)

    payload = json.loads(calls[0][2])
    assert payload["status"] == "n/a"
    assert payload["telegram_message_id"] is None


def test_get_processed_message_returns_none_when_missing(monkeypatch):
    monkeypatch.setattr(state_service, "_redis_command", lambda *args: None)
    assert state_service.get_processed_message("missing") is None


def test_get_processed_message_returns_parsed_doc(monkeypatch):
    stored = json.dumps({"message_id": "abc", "status": "pending"})
    monkeypatch.setattr(state_service, "_redis_command", lambda *args: stored)
    doc = state_service.get_processed_message("abc")
    assert doc == {"message_id": "abc", "status": "pending"}


def test_mark_alert_answered_updates_status(monkeypatch):
    existing = json.dumps({"message_id": "abc", "status": "pending", "telegram_message_id": 5})
    calls = []

    def fake_command(*args):
        calls.append(args)
        if args[0] == "GET":
            return existing
        return "OK"

    monkeypatch.setattr(state_service, "_redis_command", fake_command)

    result = state_service.mark_alert_answered("abc")

    assert result["status"] == "answered"
    set_call = next(c for c in calls if c[0] == "SET")
    payload = json.loads(set_call[2])
    assert payload["status"] == "answered"


def test_mark_alert_answered_returns_none_when_no_state(monkeypatch):
    monkeypatch.setattr(state_service, "_redis_command", lambda *args: None)
    assert state_service.mark_alert_answered("missing") is None


def test_mark_alert_dismissed_updates_status(monkeypatch):
    existing = json.dumps({"message_id": "abc", "status": "pending", "telegram_message_id": 5})

    def fake_command(*args):
        if args[0] == "GET":
            return existing
        return "OK"

    monkeypatch.setattr(state_service, "_redis_command", fake_command)

    result = state_service.mark_alert_dismissed("abc")

    assert result["status"] == "dismissed"


def test_get_telegram_update_offset_defaults_to_zero(monkeypatch):
    monkeypatch.setattr(state_service, "_redis_command", lambda *args: None)
    assert state_service.get_telegram_update_offset() == 0


def test_save_and_get_telegram_update_offset(monkeypatch):
    store = {}

    def fake_command(*args):
        if args[0] == "GET":
            return store.get("state")
        if args[0] == "SET":
            store["state"] = args[2]
        return "OK"

    monkeypatch.setattr(state_service, "_redis_command", fake_command)

    state_service.save_telegram_update_offset(42)
    assert state_service.get_telegram_update_offset() == 42
