import telegram_service as ts


class _FakeResponse:
    def __init__(self, status_code, result=None):
        self.status_code = status_code
        self._result = result if result is not None else {"message_id": 555}

    def json(self):
        return {"result": self._result}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")


def _email(**overrides):
    base = {
        "message_id": "abc123",
        "sender": "rrhh@universidad.edu",
        "subject": "Entrevista",
        "snippet": "Confirma tu disponibilidad",
        "gmail_link": "https://mail.google.com/mail/u/0/#inbox/abc123",
    }
    base.update(overrides)
    return base


def _classification(**overrides):
    base = {
        "score": 9,
        "reason": "Solicitud urgente",
        "category": "entrevista",
        "requires_action": True,
        "urgency": "critical",
    }
    base.update(overrides)
    return base


def test_format_alert_message_does_not_embed_raw_link():
    text = ts.format_alert_message(_email(), _classification())
    assert "Abrir en Gmail" not in text
    assert "mail.google.com" not in text


def test_format_alert_message_has_score_header_and_divider():
    text = ts.format_alert_message(_email(), _classification())
    lines = text.split("\n")
    assert "CORREO IMPORTANTE" in lines[0]
    assert "9/10" in lines[0]
    assert lines[1] == ts._DIVIDER


def test_format_alert_message_translates_urgency_to_spanish():
    text = ts.format_alert_message(_email(), _classification(urgency="critical"))
    assert "Crítica" in text
    assert "critical" not in text


def test_format_alert_message_uses_blockquote_for_snippet():
    text = ts.format_alert_message(_email(snippet="Texto del correo"), _classification())
    assert any(line.startswith("> ") for line in text.split("\n"))


def test_format_alert_message_omits_blockquote_when_no_snippet():
    text = ts.format_alert_message(_email(snippet=""), _classification())
    assert not any(line.startswith(">") for line in text.split("\n"))


def test_gmail_button_has_single_button():
    button = ts._gmail_button("https://mail.google.com/mail/u/0/#inbox/abc123")
    assert button == {
        "inline_keyboard": [
            [{"text": "📧 Abrir en Gmail", "url": "https://mail.google.com/mail/u/0/#inbox/abc123"}]
        ]
    }


def test_gmail_button_returns_none_for_empty_link():
    assert ts._gmail_button("") is None


def test_send_alert_includes_button_and_returns_message_id(monkeypatch):
    calls = []

    def fake_post(url, json, timeout):
        calls.append((url, json))
        return _FakeResponse(200, {"message_id": 777})

    monkeypatch.setattr(ts.config, "get_telegram_bot_token", lambda: "token")
    monkeypatch.setattr(ts.config, "get_telegram_chat_id", lambda: "123")
    monkeypatch.setattr(ts.requests, "post", fake_post)

    result = ts.send_alert(_email(), _classification())

    send_json = next(j for url, j in calls if url.endswith("sendMessage"))
    assert result == 777
    assert "reply_markup" in send_json
    assert send_json["reply_markup"]["inline_keyboard"][0][0]["url"] == (
        "https://mail.google.com/mail/u/0/#inbox/abc123"
    )


def test_send_alert_sets_pending_reaction_after_sending(monkeypatch):
    calls = []

    def fake_post(url, json, timeout):
        calls.append((url, json))
        return _FakeResponse(200, {"message_id": 777})

    monkeypatch.setattr(ts.config, "get_telegram_bot_token", lambda: "token")
    monkeypatch.setattr(ts.config, "get_telegram_chat_id", lambda: "123")
    monkeypatch.setattr(ts.requests, "post", fake_post)

    ts.send_alert(_email(), _classification())

    reaction_call = next(c for c in calls if c[0].endswith("setMessageReaction"))
    assert reaction_call[1]["message_id"] == 777
    assert reaction_call[1]["reaction"] == [{"type": "emoji", "emoji": "👀"}]


def test_send_alert_falls_back_to_plain_text_keeping_button(monkeypatch):
    calls = []

    def fake_post(url, json, timeout):
        calls.append((url, json))
        if url.endswith("setMessageReaction"):
            return _FakeResponse(200)
        if json.get("parse_mode") == "MarkdownV2":
            return _FakeResponse(400)
        return _FakeResponse(200, {"message_id": 42})

    monkeypatch.setattr(ts.config, "get_telegram_bot_token", lambda: "token")
    monkeypatch.setattr(ts.config, "get_telegram_chat_id", lambda: "123")
    monkeypatch.setattr(ts.requests, "post", fake_post)

    result = ts.send_alert(_email(), _classification())

    send_calls = [j for url, j in calls if url.endswith("sendMessage")]
    assert result == 42
    assert len(send_calls) == 2
    assert "reply_markup" in send_calls[0]
    assert "reply_markup" in send_calls[1]


def test_set_reaction_sends_emoji(monkeypatch):
    captured = {}

    def fake_post(method, payload):
        captured["method"] = method
        captured["payload"] = payload
        return _FakeResponse(200)

    monkeypatch.setattr(ts, "_post", fake_post)

    result = ts.set_reaction(10, "👀")

    assert result is True
    assert captured["method"] == "setMessageReaction"
    assert captured["payload"]["reaction"] == [{"type": "emoji", "emoji": "👀"}]


def test_set_reaction_none_clears_reaction(monkeypatch):
    captured = {}

    def fake_post(method, payload):
        captured["payload"] = payload
        return _FakeResponse(200)

    monkeypatch.setattr(ts, "_post", fake_post)

    ts.set_reaction(10, None)

    assert captured["payload"]["reaction"] == []


def test_set_reaction_returns_false_on_error(monkeypatch):
    monkeypatch.setattr(ts, "_post", lambda method, payload: _FakeResponse(400))
    assert ts.set_reaction(10, "👀") is False


def test_send_alert_returns_none_when_both_attempts_fail(monkeypatch):
    monkeypatch.setattr(ts.config, "get_telegram_bot_token", lambda: "token")
    monkeypatch.setattr(ts.config, "get_telegram_chat_id", lambda: "123")
    monkeypatch.setattr(ts.requests, "post", lambda url, json, timeout: _FakeResponse(400))

    result = ts.send_alert(_email(), _classification())

    assert result is None


def test_get_updates_requests_message_reaction_via_post(monkeypatch):
    captured = {}

    def fake_post(method, payload):
        captured["method"] = method
        captured["payload"] = payload
        return _FakeResponse(200, [{"update_id": 10}])

    monkeypatch.setattr(ts, "_post", fake_post)

    result = ts.get_updates(5)

    assert result == [{"update_id": 10}]
    assert captured["method"] == "getUpdates"
    assert captured["payload"]["offset"] == 5
    assert captured["payload"]["allowed_updates"] == ["message_reaction"]
