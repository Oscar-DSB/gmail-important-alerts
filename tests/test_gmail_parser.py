import base64

from gmail_parser import build_gmail_link, html_to_text, parse_message


def _b64url(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


def _headers(**kwargs):
    return [{"name": k, "value": v} for k, v in kwargs.items()]


def test_parse_message_text_plain():
    message = {
        "id": "msg1",
        "threadId": "thread1",
        "labelIds": ["INBOX"],
        "snippet": "Hola mundo",
        "payload": {
            "headers": _headers(From="a@example.com", To="b@example.com", Subject="Asunto", Date="Mon, 1 Jan 2026 10:00:00 +0000"),
            "mimeType": "text/plain",
            "body": {"data": _b64url("Contenido en texto plano")},
        },
    }

    result = parse_message(message)

    assert result["message_id"] == "msg1"
    assert result["thread_id"] == "thread1"
    assert result["sender"] == "a@example.com"
    assert result["subject"] == "Asunto"
    assert result["body_text"] == "Contenido en texto plano"
    assert result["labels"] == ["INBOX"]


def test_parse_message_html_only():
    html = "<html><body><p>Hola <b>mundo</b></p></body></html>"
    message = {
        "id": "msg2",
        "threadId": "thread2",
        "payload": {
            "headers": _headers(Subject="HTML"),
            "mimeType": "text/html",
            "body": {"data": _b64url(html)},
        },
    }

    result = parse_message(message)

    assert "Hola" in result["body_text"]
    assert "mundo" in result["body_text"]
    assert "<b>" not in result["body_text"]


def test_parse_message_multipart_prefers_plain():
    message = {
        "id": "msg3",
        "threadId": "thread3",
        "payload": {
            "headers": _headers(Subject="Multipart"),
            "mimeType": "multipart/alternative",
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": _b64url("Texto plano preferido")},
                },
                {
                    "mimeType": "text/html",
                    "body": {"data": _b64url("<p>HTML alternativo</p>")},
                },
            ],
        },
    }

    result = parse_message(message)

    assert result["body_text"] == "Texto plano preferido"


def test_parse_message_multipart_mixed_nested():
    message = {
        "id": "msg4",
        "threadId": "thread4",
        "payload": {
            "headers": _headers(Subject="Nested"),
            "mimeType": "multipart/mixed",
            "parts": [
                {
                    "mimeType": "multipart/alternative",
                    "parts": [
                        {
                            "mimeType": "text/plain",
                            "body": {"data": _b64url("Anidado texto plano")},
                        }
                    ],
                },
                {
                    "mimeType": "application/pdf",
                    "body": {"data": _b64url("binario-simulado")},
                },
            ],
        },
    }

    result = parse_message(message)

    assert result["body_text"] == "Anidado texto plano"


def test_parse_message_without_body():
    message = {
        "id": "msg5",
        "threadId": "thread5",
        "payload": {"headers": _headers(Subject="Sin cuerpo"), "mimeType": "text/plain", "body": {}},
    }

    result = parse_message(message)

    assert result["body_text"] == ""
    assert result["subject"] == "Sin cuerpo"


def test_parse_message_missing_headers():
    message = {
        "id": "msg6",
        "threadId": "thread6",
        "payload": {"headers": [], "mimeType": "text/plain", "body": {}},
    }

    result = parse_message(message)

    assert result["sender"] == ""
    assert result["subject"] == ""
    assert result["date"] == ""


def test_html_to_text_strips_scripts():
    html = "<html><head><script>evil()</script></head><body>Texto real</body></html>"
    assert html_to_text(html) == "Texto real"


def test_build_gmail_link():
    assert build_gmail_link("abc123") == "https://mail.google.com/mail/u/0/#inbox/abc123"


def test_parse_message_decodes_html_entities_in_snippet_and_subject():
    message = {
        "id": "msg7",
        "threadId": "thread7",
        "snippet": "Necesito que confirmes tu disponibilidad &quot;antes de las 18h&quot;",
        "payload": {
            "headers": _headers(
                From="Oscar De Simone &lt;oscardsb22@gmail.com&gt;",
                Subject="Entrevista &amp; confirmaci&#243;n urgente",
            ),
            "mimeType": "text/plain",
            "body": {"data": _b64url("cuerpo")},
        },
    }

    result = parse_message(message)

    assert result["snippet"] == 'Necesito que confirmes tu disponibilidad "antes de las 18h"'
    assert result["sender"] == "Oscar De Simone <oscardsb22@gmail.com>"
    assert result["subject"] == "Entrevista & confirmación urgente"
