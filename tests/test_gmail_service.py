import pytest

import gmail_service


class _FakeExecutable:
    def __init__(self, response):
        self._response = response

    def execute(self):
        return self._response


class _FakeHistory:
    def __init__(self, responses_by_page_token):
        self._responses = responses_by_page_token

    def list(self, **kwargs):
        page_token = kwargs.get("pageToken")
        return _FakeExecutable(self._responses[page_token])


class _FakeUsers:
    def __init__(self, responses_by_page_token):
        self._history = _FakeHistory(responses_by_page_token)

    def history(self):
        return self._history


class _FakeService:
    def __init__(self, responses_by_page_token):
        self._users = _FakeUsers(responses_by_page_token)

    def users(self):
        return self._users


def test_list_new_message_ids_returns_historyid_from_response():
    """Regresión: el historyId devuelto debe ser el que Gmail reporta en la
    propia respuesta de history.list (snapshot ANTES de procesar mensajes),
    no uno pedido después de procesar. Ver docstring de list_new_message_ids."""
    response = {
        "history": [
            {"messagesAdded": [{"message": {"id": "msg1"}}]},
        ],
        "historyId": "555000",
    }
    service = _FakeService({None: response})

    message_ids, latest_history_id = gmail_service.list_new_message_ids(service, "100")

    assert message_ids == ["msg1"]
    assert latest_history_id == "555000"


def test_list_new_message_ids_paginates_and_keeps_last_page_historyid():
    page1 = {
        "history": [{"messagesAdded": [{"message": {"id": "msg1"}}]}],
        "historyId": "200",
        "nextPageToken": "page2",
    }
    page2 = {
        "history": [{"messagesAdded": [{"message": {"id": "msg2"}}]}],
        "historyId": "300",
    }
    service = _FakeService({None: page1, "page2": page2})

    message_ids, latest_history_id = gmail_service.list_new_message_ids(service, "100")

    assert message_ids == ["msg1", "msg2"]
    assert latest_history_id == "300"


def test_list_new_message_ids_dedupes_message_ids():
    response = {
        "history": [
            {"messagesAdded": [{"message": {"id": "msg1"}}, {"message": {"id": "msg1"}}]},
        ],
        "historyId": "999",
    }
    service = _FakeService({None: response})

    message_ids, _ = gmail_service.list_new_message_ids(service, "100")

    assert message_ids == ["msg1"]


def test_list_new_message_ids_falls_back_to_start_history_id_if_missing():
    response = {"history": []}
    service = _FakeService({None: response})

    message_ids, latest_history_id = gmail_service.list_new_message_ids(service, "100")

    assert message_ids == []
    assert latest_history_id == "100"
