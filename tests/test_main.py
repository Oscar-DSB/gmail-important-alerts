import main


def test_process_telegram_reactions_noop_when_no_updates(monkeypatch):
    monkeypatch.setattr(main.state_service, "get_telegram_update_offset", lambda: 5)
    monkeypatch.setattr(main.telegram_service, "get_updates", lambda offset: [])

    saved = []
    monkeypatch.setattr(main.state_service, "save_telegram_update_offset", lambda o: saved.append(o))

    main.process_telegram_reactions()

    assert saved == []


def _reaction_update(update_id, telegram_message_id, emoji, *, is_bot=False):
    return {
        "update_id": update_id,
        "message_reaction": {
            "message_id": telegram_message_id,
            "user": {"is_bot": is_bot},
            "new_reaction": [{"type": "emoji", "emoji": emoji}],
        },
    }


def _patch_reaction_cleared(monkeypatch):
    cleared = []
    monkeypatch.setattr(
        main.telegram_service,
        "set_reaction",
        lambda tid, emoji: cleared.append((tid, emoji)),
    )
    return cleared


def test_process_telegram_reactions_marks_answered_on_thumbs_up(monkeypatch):
    update = _reaction_update(100, 555, "👍")
    monkeypatch.setattr(main.state_service, "get_telegram_update_offset", lambda: 0)
    monkeypatch.setattr(main.telegram_service, "get_updates", lambda offset: [update])
    monkeypatch.setattr(
        main.state_service, "get_gmail_message_id_for_telegram", lambda tid: "msg1"
    )
    monkeypatch.setattr(
        main.state_service, "get_processed_message", lambda mid: {"status": "pending"}
    )
    answered = []
    monkeypatch.setattr(main.state_service, "mark_alert_answered", lambda mid: answered.append(mid))
    cleared = _patch_reaction_cleared(monkeypatch)
    saved_offset = []
    monkeypatch.setattr(
        main.state_service, "save_telegram_update_offset", lambda o: saved_offset.append(o)
    )

    main.process_telegram_reactions()

    assert answered == ["msg1"]
    assert cleared == [(555, None)]
    assert saved_offset == [101]


def test_process_telegram_reactions_marks_dismissed_on_thumbs_down(monkeypatch):
    update = _reaction_update(101, 556, "👎")
    monkeypatch.setattr(main.state_service, "get_telegram_update_offset", lambda: 0)
    monkeypatch.setattr(main.telegram_service, "get_updates", lambda offset: [update])
    monkeypatch.setattr(
        main.state_service, "get_gmail_message_id_for_telegram", lambda tid: "msg2"
    )
    monkeypatch.setattr(
        main.state_service, "get_processed_message", lambda mid: {"status": "pending"}
    )
    dismissed = []
    monkeypatch.setattr(main.state_service, "mark_alert_dismissed", lambda mid: dismissed.append(mid))
    _patch_reaction_cleared(monkeypatch)
    monkeypatch.setattr(main.state_service, "save_telegram_update_offset", lambda o: None)

    main.process_telegram_reactions()

    assert dismissed == ["msg2"]


def test_process_telegram_reactions_ignores_bots_own_reaction(monkeypatch):
    update = _reaction_update(150, 560, "👀", is_bot=True)
    monkeypatch.setattr(main.state_service, "get_telegram_update_offset", lambda: 0)
    monkeypatch.setattr(main.telegram_service, "get_updates", lambda offset: [update])

    called = []
    monkeypatch.setattr(
        main.state_service, "get_gmail_message_id_for_telegram", lambda tid: called.append(tid)
    )
    monkeypatch.setattr(main.state_service, "save_telegram_update_offset", lambda o: None)

    main.process_telegram_reactions()

    assert called == []  # la reacción del propio bot nunca se interpreta como respuesta


def test_process_telegram_reactions_ignores_unrelated_emoji(monkeypatch):
    update = _reaction_update(102, 557, "❤")
    monkeypatch.setattr(main.state_service, "get_telegram_update_offset", lambda: 0)
    monkeypatch.setattr(main.telegram_service, "get_updates", lambda offset: [update])

    called = []
    monkeypatch.setattr(
        main.state_service, "get_gmail_message_id_for_telegram", lambda tid: called.append(tid)
    )
    monkeypatch.setattr(main.state_service, "save_telegram_update_offset", lambda o: None)

    main.process_telegram_reactions()

    assert called == []  # nunca llega a buscar el mensaje: el emoji no es de interés


def test_process_telegram_reactions_ignores_untracked_telegram_message(monkeypatch):
    update = _reaction_update(103, 999, "👍")
    monkeypatch.setattr(main.state_service, "get_telegram_update_offset", lambda: 0)
    monkeypatch.setattr(main.telegram_service, "get_updates", lambda offset: [update])
    monkeypatch.setattr(main.state_service, "get_gmail_message_id_for_telegram", lambda tid: None)

    answered = []
    monkeypatch.setattr(main.state_service, "mark_alert_answered", lambda mid: answered.append(mid))
    monkeypatch.setattr(main.state_service, "save_telegram_update_offset", lambda o: None)

    main.process_telegram_reactions()

    assert answered == []


def test_process_telegram_reactions_ignores_already_resolved_message(monkeypatch):
    update = _reaction_update(104, 558, "👍")
    monkeypatch.setattr(main.state_service, "get_telegram_update_offset", lambda: 0)
    monkeypatch.setattr(main.telegram_service, "get_updates", lambda offset: [update])
    monkeypatch.setattr(
        main.state_service, "get_gmail_message_id_for_telegram", lambda tid: "msg3"
    )
    monkeypatch.setattr(
        main.state_service, "get_processed_message", lambda mid: {"status": "answered"}
    )
    answered = []
    monkeypatch.setattr(main.state_service, "mark_alert_answered", lambda mid: answered.append(mid))
    monkeypatch.setattr(main.state_service, "save_telegram_update_offset", lambda o: None)

    main.process_telegram_reactions()

    assert answered == []


def test_process_telegram_reactions_advances_offset_past_unrelated_updates(monkeypatch):
    update = {"update_id": 9}  # update sin message_reaction
    monkeypatch.setattr(main.state_service, "get_telegram_update_offset", lambda: 0)
    monkeypatch.setattr(main.telegram_service, "get_updates", lambda offset: [update])

    saved_offset = []
    monkeypatch.setattr(
        main.state_service, "save_telegram_update_offset", lambda o: saved_offset.append(o)
    )

    main.process_telegram_reactions()

    assert saved_offset == [10]
