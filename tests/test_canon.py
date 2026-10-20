"""The open-threads list: what stays open, what closes, and what the agents are shown."""

from engine import canon


def _note(open_threads=(), closes=()):
    return {
        "summary": "s",
        "changes": [],
        "open_threads": list(open_threads),
        "closes": list(closes),
    }


def test_a_thread_stays_open_until_an_episode_closes_it(monkeypatch):
    produced = [
        (3, "First", True, _note(["Who left the letter?", "Will he go back?"])),
        (4, "Second", False, _note(["Who rang the bell?"])),
        (7, "Third", False, _note([], closes=["T3.2"])),
        (8, "Older note", False, {}),  # produced before canon notes existed
    ]
    monkeypatch.setattr(canon, "_produced", lambda session: produced)

    threads = canon.open_threads(None)

    assert [(t.id, t.episode, t.dreams) for t in threads] == [
        ("T3.1", "First", True),
        ("T4.1", "Second", False),
    ]


def test_old_threads_beyond_the_cap_are_hidden_except_lost_dreams_ones(monkeypatch):
    dreams = canon.OpenThread("T1.1", "Pilot step", "q", dreams=True)
    others = [
        canon.OpenThread(f"T{n}.1", f"Ep {n}", "q") for n in range(2, 2 + canon.OPEN_THREADS + 5)
    ]

    shown = canon._shown([dreams, *others])

    assert shown[0] == dreams  # however old
    assert len(shown) == 1 + canon.OPEN_THREADS
    assert shown[-1] == others[-1] and others[0] not in shown  # newest kept, oldest hidden


def _pick_leads(cards: list[dict], days: int) -> list[str]:
    """Run `days` picks that each take the lead they're given."""
    picked = []
    for _ in range(days):
        lead, _ = canon.choose_lead(cards)
        cards.append({"lead": lead})
        picked.append(lead)
    return picked


def test_before_they_meet_tina_leads_about_two_in_three():
    picked = _pick_leads([], 20)

    assert picked[:5] == ["tina", "fann", "tina", "tina", "fann"]
    assert picked.count("tina") == 13 and picked.count("fann") == 7
    assert "both" not in picked


def test_from_the_meeting_the_mix_restarts_with_them_together():
    cards = [{"lead": "tina"}] * 9 + [
        {"lead": "both", "advances_dreams_thread": True, "dreams_step": canon.MEETING_STEP}
    ]

    picked = _pick_leads(cards, 10)

    assert (picked.count("both"), picked.count("tina"), picked.count("fann")) == (4, 3, 3)
    assert picked[0] == "both"  # the earlier Tina episodes don't count against the new mix


def test_cards_from_before_leads_dont_count():
    lead, note = canon.choose_lead([{"mode": "mixed"}, {"lead": ""}, {"lead": "tina"}])

    assert lead == "fann"
    assert "Leads so far: tina 1, fann 0 (target tina 65%, fann 35%)" in note
    assert f"a card that tells {canon.MEETING_STEP}, which has lead 'both'" in note
