"""The story studio: the agents that turn a premise into an episode.

Story first: story architect -> script writer -> critic, each reading the story so far
(engine/canon.py) so episodes connect. Production, once the owner has the
script: visual director -> packager. Each agent returns one contract (engine/llm/schemas.py). When
an answer breaks its contract, the agent gets its answer back with the errors and tries again, up
to MAX_ATTEMPTS calls in all.

The studio only talks to the model through `call`, so the pipeline (StageContext.llm_json, with
the daily spend cap) and the eval harness can each supply their own. Every call names its agent
role, which picks that agent's model and effort (Settings.llm_for).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel

from engine.llm.client import LLMOutputInvalid
from engine.llm.prompts import system_prompt
from engine.llm.schemas import (
    DURATION_TOLERANCE_S,
    PACE_WPM,
    CandidateCard,
    CriticIssue,
    CriticReport,
    Episode,
    Package,
    Script,
    Storyboard,
    StoryCard,
    StoryCards,
    api_schema,
    check_speakers,
)

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
MAX_ERROR_CHARS = 3000


class JSONCall(Protocol):
    def __call__[M: BaseModel](
        self, *, system: str, user: str, schema: dict[str, Any], model: type[M], role: str
    ) -> M: ...


@dataclass(frozen=True)
class Candidate:
    ref: str
    title: str
    premise: str
    universe: str
    recurring: list[str] = field(default_factory=list)


def _json(model: BaseModel) -> str:
    return json.dumps(model.model_dump(mode="json"), indent=1, ensure_ascii=False)


def _section(tag: str, body: str) -> str:
    return f"<{tag}>\n{body}\n</{tag}>"


def _notes(issues: Sequence[CriticIssue]) -> str:
    lines = [
        f"- [{i.severity}] {i.area}" + (f", rule {i.rule}" if i.rule else "") + f": {i.problem} "
        f"Fix: {i.fix}"
        for i in issues
    ]
    return _section("critic_notes", "\n".join(lines))


def _canon(canon: Sequence[str]) -> str:
    return _section("story_so_far", "\n".join(f"- {c}" for c in canon))


def _owner_notes(notes: Sequence[str]) -> str:
    return _section("owner_notes", "\n".join(f"- {n}" for n in notes))


def revision_notes(report: CriticReport) -> list[CriticIssue]:
    """What a revision must fix: the high issues, or every issue when none is high."""
    return [i for i in report.issues if i.severity == "high"] or list(report.issues)


@dataclass
class Studio:
    call: JSONCall
    brand_dir: Path
    repairs: int = 0  # contract-repair retries so far, for logs and evals

    def _ask[M: BaseModel](
        self,
        role: str,
        user: str,
        model: type[M],
        check: Callable[[M], None] | None = None,
    ) -> M:
        system = system_prompt(role, self.brand_dir)
        schema = api_schema(model)
        prompt = user
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                out = self.call(system=system, user=prompt, schema=schema, model=model, role=role)
                if check:
                    try:
                        check(out)
                    except ValueError as e:
                        raise LLMOutputInvalid(str(e), data=out.model_dump(mode="json")) from e
                return out
            except LLMOutputInvalid as e:
                if attempt == MAX_ATTEMPTS:
                    raise
                self.repairs += 1
                log.warning(
                    "contract broken; asking for a repair",
                    extra={"role": role, "attempt": attempt, "error": str(e)[:500]},
                )
                prompt = _repair_prompt(user, e)
        raise AssertionError("unreachable")

    # ---------------------------------------------------------------- story

    def cards(
        self,
        candidates: Sequence[Candidate],
        *,
        new: int = 0,
        universe: str = "urban",
        recent_titles: Sequence[str] = (),
        canon: Sequence[str] = (),
        mix: str = "",
    ) -> list[CandidateCard]:
        """`canon`: the story so far (engine/canon.py); `mix`: how recent picks split."""
        parts = []
        if candidates:
            lines = []
            for c in candidates:
                uses = f" Uses: {', '.join(c.recurring)}." if c.recurring else ""
                lines.append(f"- ref {c.ref} ({c.universe}): {c.title}. {c.premise}{uses}")
            parts.append(_section("candidates", "\n".join(lines)))
        if new:
            parts.append(
                f"Also write {new} new, original premise(s) in the {universe} universe, ref 'new'."
            )
        if recent_titles:
            parts.append(_section("recently_produced", "\n".join(f"- {t}" for t in recent_titles)))
        if canon:
            parts.append(_canon(canon))
        if mix:
            parts.append(_section("recent_mix", mix))
        parts.append("Return the story cards.")

        refs = [c.ref for c in candidates]

        def check(out: StoryCards) -> None:
            got = [c.ref for c in out.cards if c.ref != "new"]
            if sorted(got) != sorted(refs):
                raise ValueError(f"need one card per candidate ref {refs}; got {got}")
            if sum(c.ref == "new" for c in out.cards) < new:
                raise ValueError(f"need {new} card(s) with ref 'new'")

        return self._ask("story_architect", "\n\n".join(parts), StoryCards, check).cards

    def script(
        self,
        card: StoryCard,
        *,
        previous: Script | None = None,
        notes: Sequence[CriticIssue] = (),
        owner_notes: Sequence[str] = (),
        canon: Sequence[str] = (),
    ) -> Script:
        """`owner_notes`: why the owner turned down today's earlier stories (/redo)."""
        parts = [_section("story_card", _json(card))]
        if canon:
            parts.append(_canon(canon))
        if owner_notes:
            parts += [
                _owner_notes(owner_notes),
                "The owner turned down today's earlier story. Let their notes shape this script.",
            ]
        if previous is None:
            parts.append("Write the script.")
        else:
            # a revision of the last draft rather than a fresh one, so what worked survives
            parts += [
                _section("previous_draft", _json(previous)),
                _notes(notes),
                "Revise your previous draft so it addresses every critic note. Keep what works.",
            ]

        def check(out: Script) -> None:
            check_speakers(card.mode, out)

        return self._ask("script_writer", "\n\n".join(parts), Script, check)

    def review(
        self,
        card: StoryCard,
        script: Script,
        owner_notes: Sequence[str] = (),
        canon: Sequence[str] = (),
    ) -> CriticReport:
        """The story review: card and script, before any money goes into visuals."""
        parts = [
            _section("story_card", _json(card)),
            _section("script", _json(script)),
            f"Spoken: {script.word_count} words, about {script.estimated_duration_s:.0f} seconds.",
        ]
        if canon:
            parts.append(_canon(canon))
        if owner_notes:
            parts += [
                _owner_notes(owner_notes),
                "The owner turned down today's earlier story with these notes. Check that this "
                "script answers them too.",
            ]
        parts.append("Review the story and script.")
        return self._ask("critic", "\n\n".join(parts), CriticReport)

    def revise_script(
        self,
        card: StoryCard,
        script: Script,
        report: CriticReport,
        owner_notes: Sequence[str] = (),
        canon: Sequence[str] = (),
    ) -> Script:
        return self.script(
            card,
            previous=script,
            notes=revision_notes(report),
            owner_notes=owner_notes,
            canon=canon,
        )

    # ---------------------------------------------------------------- production

    def storyboard(self, card: StoryCard, script: Script) -> Storyboard:
        target = script.estimated_duration_s
        user = "\n\n".join(
            [
                _section("story_card", _json(card)),
                _section("script", _json(script)),
                f"The narration runs about {target:.0f} seconds ({script.word_count} words at "
                f"{PACE_WPM} wpm, plus pauses). The last shot must end between "
                f"{target - DURATION_TOLERANCE_S:.0f} and {target + DURATION_TOLERANCE_S:.0f} s.",
                "Write the storyboard.",
            ]
        )

        def check(board: Storyboard) -> None:
            if abs(board.duration_s - target) > DURATION_TOLERANCE_S:
                raise ValueError(
                    f"the last shot ends at {board.duration_s:.1f}s but the narration needs "
                    f"~{target:.0f}s; retime the shots"
                )

        return self._ask("visual_director", user, Storyboard, check)

    def package(self, card: StoryCard, script: Script, board: Storyboard) -> Package:
        user = "\n\n".join(
            [
                _section("story_card", _json(card)),
                _section("script", _json(script)),
                _section("storyboard", _json(board)),
                "Write the package.",
            ]
        )

        def check(pkg: Package) -> None:
            Episode(id="check", card=card, script=script, storyboard=board, package=pkg)

        return self._ask("packager", user, Package, check)


def _repair_prompt(user: str, error: LLMOutputInvalid) -> str:
    parts = [user]
    if error.data is not None:
        parts.append(_section("previous_answer", json.dumps(error.data, ensure_ascii=False)))
    parts.append(_section("errors", str(error)[:MAX_ERROR_CHARS]))
    parts.append(
        "Your previous answer broke the contract. Return the complete answer again with these "
        "errors fixed, keeping everything that was fine."
    )
    return "\n\n".join(parts)
