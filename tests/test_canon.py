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
