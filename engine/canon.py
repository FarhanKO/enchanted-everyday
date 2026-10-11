"""The story so far: what connects the episodes.

Every produced episode leaves a canon note (Package.canon: what happened, what is now true, what is
still open). The story agents read three things, gathered by `load`:

- the latest notes, so a new episode can call back to an earlier one and never contradicts it;
- the open threads: every question an episode left open that no later one has answered, however
  old, each with an id the packager uses to close it (CanonNote.closes);
- the lost-dreams thread: which steps of brand/dreams_thread.md have been told, and which one may
  be told today.

The pilot (s000) is in the story bible and the season plan, so it needs no note here.

`recent_mix` tells the story architect how recent picks split across modes and story types, so it
can steer toward the mix targets in the story bible.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from engine.db.models import Idea
from engine.db.models import Script as ScriptRow

CANON_EPISODES = 8  # latest produced episodes every story agent sees in full
OPEN_THREADS = 20  # open threads shown besides the lost-dreams ones, newest first
MIX_WINDOW = 10  # picks the mix is measured over
MODE_TARGET = {"mixed": 0.65, "dialogue": 0.2, "narrated": 0.15}  # Farhan, 2026-10-12
USED = ("picked", "published")  # ideas that count as told
DREAMS_FILE = "dreams_thread.md"
STEP = re.compile(r"^### (D\d+)\. (.+)$", re.MULTILINE)


@dataclass(frozen=True)
class OpenThread:
    id: str  # T<script row id>.<n>: stable, so a later episode can close it
    episode: str
    question: str
    dreams: bool = False  # left by a lost-dreams episode: always shown


@dataclass(frozen=True)
class Canon:
    episodes: Sequence[str] = ()  # one line per recent produced episode, oldest first
    threads: Sequence[OpenThread] = ()  # still open, oldest first
    hidden_threads: int = 0  # open threads left out to keep the prompt short
    dreams: str = ""  # the lost-dreams thread: told steps and today's step
    next_step: str | None = None  # the step a card may tell today; None while the thread rests
    thread_ids: frozenset[str] = field(default_factory=frozenset)  # every open id, shown or not


def load(session: Session, brand_dir: Path) -> Canon:
    threads = open_threads(session)
    shown = _shown(threads)
    status, next_step = dreams_status(session, brand_dir)
    return Canon(
        episodes=story_so_far(session),
        threads=shown,
        hidden_threads=len(threads) - len(shown),
        dreams=status,
        next_step=next_step,
        thread_ids=frozenset(t.id for t in threads),
    )


def _produced(session: Session) -> list[tuple[int, str, bool, dict[str, Any]]]:
    """(script id, title, moved the lost-dreams thread, canon note) per produced episode, oldest
    first. The note is {} for episodes produced before canon notes existed."""
    rows = session.execute(
        select(
            ScriptRow.id,
            Idea.title,
            Idea.card["advances_dreams_thread"],
            ScriptRow.package["canon"],
        )
        .join(Idea, ScriptRow.idea_id == Idea.id)
        .where(ScriptRow.package.is_not(None))
        .order_by(ScriptRow.id)
    ).all()
    return [(i, title, bool(dreams), canon or {}) for i, title, dreams, canon in rows]


def story_so_far(session: Session, limit: int = CANON_EPISODES) -> list[str]:
    """One line per recent produced episode, oldest first. Open questions are listed separately."""
    lines = []
    for _, title, _, canon in _produced(session)[-limit:]:
        if not canon:
            continue  # produced before canon notes existed
        line = f"{title}: {canon['summary']}"
        if canon.get("changes"):
            line += f" Now true: {'; '.join(canon['changes'])}."
        lines.append(line)
    return lines


def open_threads(session: Session) -> list[OpenThread]:
    """Every question an episode left open and no later episode closed, oldest first."""
    threads: list[OpenThread] = []
    closed: set[str] = set()
    for script_id, title, dreams, canon in _produced(session):
        closed.update(canon.get("closes", []))
        threads += [
            OpenThread(
                id=f"T{script_id}.{n}",
                episode=title,
                question=q,
                dreams=dreams,
            )
            for n, q in enumerate(canon.get("open_threads", []), start=1)
        ]
    return [t for t in threads if t.id not in closed]


def _shown(threads: list[OpenThread]) -> list[OpenThread]:
    """The lost-dreams threads, plus the newest OPEN_THREADS others, in their original order."""
    others = [t for t in threads if not t.dreams][-OPEN_THREADS:]
    keep = {t.id for t in others}
    return [t for t in threads if t.dreams or t.id in keep]


def dreams_steps(brand_dir: Path) -> list[tuple[str, str]]:
    """(id, title) for every step in the season plan, in telling order."""
    path = Path(brand_dir) / DREAMS_FILE
    if not path.exists():
        return []
    return STEP.findall(path.read_text(encoding="utf-8"))


def _recent_cards(session: Session, window: int) -> list[dict[str, Any]]:
    """The latest picks' cards, newest first."""
    cards = session.scalars(
        select(Idea.card)
        .where(Idea.status.in_(USED))
        .order_by(Idea.created_at.desc())
        .limit(window)
    ).all()
    return [c for c in cards if c and "mode" in c]  # older cards predate modes


def _since_dreams(cards: list[dict[str, Any]]) -> int:
    """Picks since the thread last moved; len(cards) if not within them."""
    return next((i for i, c in enumerate(cards) if c.get("advances_dreams_thread")), len(cards))


def dreams_status(session: Session, brand_dir: Path) -> tuple[str, str | None]:
    """What the story architect is told about the lost-dreams thread, and today's step if any."""
    steps = dreams_steps(brand_dir)
    if not steps:
        return "", None
    told: dict[str, str] = {}  # step id -> title of the episode that told it
    for title, step in session.execute(
        select(Idea.title, Idea.card["dreams_step"].astext)
        .where(Idea.status.in_(USED), Idea.card["advances_dreams_thread"].as_boolean())
        .order_by(Idea.created_at)
    ).all():
        if step:
            told.setdefault(step, title)

    titles = dict(steps)
    lines = [
        "Told so far: "
        + (
            "; ".join(f'{sid} "{titles.get(sid, sid)}" in "{ep}"' for sid, ep in told.items())
            if told
            else "only the pilot."
        )
    ]
    upcoming = next(((sid, t) for sid, t in steps if sid not in told), None)
    latest = _recent_cards(session, 1)
    if upcoming is None:
        lines.append(
            "Every planned step is told. The thread rests: no card moves it until the owner adds "
            "steps to the season plan."
        )
        return "\n".join(lines), None
    if latest and latest[0].get("advances_dreams_thread"):  # never two in a row
        lines.append(
            f"The thread moved in the latest pick, so no card moves it today. Next time: "
            f'{upcoming[0]} "{upcoming[1]}".'
        )
        return "\n".join(lines), None
    lines.append(
        f'Next step: {upcoming[0]} "{upcoming[1]}". A card that moves the thread tells this step '
        "and no other."
    )
    return "\n".join(lines), upcoming[0]


def recent_mix(session: Session, window: int = MIX_WINDOW) -> str:
    cards = _recent_cards(session, window)
    if not cards:
        return "No recent picks yet: open with a mixed fable, then vary."
    modes = Counter(c["mode"] for c in cards)
    types = Counter(c["story_type"] for c in cards)
    since = _since_dreams(cards)
    target = ", ".join(f"{m} {round(share * 100)}%" for m, share in MODE_TARGET.items())
    return (
        f"Last {len(cards)} picks: modes "
        + ", ".join(f"{m} {modes.get(m, 0)}" for m in MODE_TARGET)
        + f" (target {target}); types "
        + ", ".join(f"{t} {types.get(t, 0)}" for t in ("fable", "daily"))
        + f". Fann's lost-dreams thread last moved {since} pick(s) ago"
        + (" or earlier." if since == len(cards) else ".")
    )
