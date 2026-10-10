"""The story so far: what connects the episodes.

Every produced episode leaves a canon note (Package.canon: what happened, what is now true, what is
still open). The story agents read the latest notes so a new episode can call back to an earlier one
and never contradicts it. The pilot (s000) is in the story bible, so it needs no note here.

`recent_mix` tells the story architect how recent picks split across modes and story types, so it
can steer toward the mix targets in the story bible.
"""

from __future__ import annotations

from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from engine.db.models import Idea
from engine.db.models import Script as ScriptRow

CANON_EPISODES = 8  # latest produced episodes every story agent sees
MIX_WINDOW = 10  # picks the mix is measured over
MODE_TARGET = {"narrated": 0.4, "mixed": 0.4, "dialogue": 0.2}


def story_so_far(session: Session, limit: int = CANON_EPISODES) -> list[str]:
    """One line per produced episode, oldest first."""
    rows = session.execute(
        select(Idea.title, ScriptRow.package)
        .join(Idea, ScriptRow.idea_id == Idea.id)
        .where(ScriptRow.package.is_not(None))
        .order_by(ScriptRow.id.desc())
        .limit(limit)
    ).all()
    lines = []
    for title, package in reversed(rows):
        canon = (package or {}).get("canon")
        if not canon:
            continue  # produced before canon notes existed
        line = f"{title}: {canon['summary']}"
        if canon.get("changes"):
            line += f" Now true: {'; '.join(canon['changes'])}."
        if canon.get("open_threads"):
            line += f" Still open: {'; '.join(canon['open_threads'])}."
        lines.append(line)
    return lines


def recent_mix(session: Session, window: int = MIX_WINDOW) -> str:
    cards = session.scalars(
        select(Idea.card)
        .where(Idea.status.in_(("picked", "published")))
        .order_by(Idea.created_at.desc())
        .limit(window)
    ).all()
    cards = [c for c in cards if c and "mode" in c]  # older cards predate modes
    if not cards:
        return "No recent picks yet: open with a narrated fable, then vary."
    modes = Counter(c["mode"] for c in cards)
    types = Counter(c["story_type"] for c in cards)
    since = next((i for i, c in enumerate(cards) if c.get("advances_dreams_thread")), len(cards))
    target = ", ".join(f"{m} {round(share * 100)}%" for m, share in MODE_TARGET.items())
    return (
        f"Last {len(cards)} picks: modes "
        + ", ".join(f"{m} {modes.get(m, 0)}" for m in MODE_TARGET)
        + f" (target {target}); types "
        + ", ".join(f"{t} {types.get(t, 0)}" for t in ("fable", "daily"))
        + f". Fann's lost-dreams thread last moved {since} pick(s) ago"
        + (" or earlier." if since == len(cards) else ".")
    )
