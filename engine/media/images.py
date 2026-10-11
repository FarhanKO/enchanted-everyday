"""Frames: one image per shot and the thumbnail, drawn by Nano Banana with the cast's references.

The prompt is the agent's shot text plus the locked descriptors and style (engine/prompting.py).
Every cast member in a shot is conditioned on their approved reference images (brand/cast.toml).
A supporting character seen in more than one shot first gets a plain-background portrait, and
their shots are conditioned on it, so they at least stay the same person within the episode
(production_style.md §3.4). The owner's /reshoot note for a frame is added to its prompt.
"""

from __future__ import annotations

import logging
import threading
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from engine import prompting
from engine.llm.schemas import Storyboard, Thumbnail
from engine.media.openrouter import Image, MediaError, image_estimate
from engine.media.paid import Ledger, cache_key

log = logging.getLogger(__name__)

Draw = Callable[[str, str, list[Path]], Image]  # (prompt, model, references) -> image
PARALLEL = 4

FRAMING = "A single vertical 9:16 illustration, one moment of a story, full bleed, no borders."
REFERENCE_NOTE = (
    "The attached images are approved reference art for {names}. Match each one's face, hair, "
    "skin tone, build and outfit exactly. Do not copy their poses, backgrounds, layout, panels or "
    "any text in them."
)
PORTRAIT = (
    "Character reference portrait: {descriptor}. Full body, standing, front view, neutral calm "
    "expression, plain pale warm-grey background, no props, no text, no labels, no frame. "
    "{character_style}"
)


@dataclass
class Frames:
    shots: dict[str, Path] = field(default_factory=dict)
    thumbnail: Path | None = None
    portraits: dict[str, Path] = field(default_factory=dict)
    cost_usd: Decimal = Decimal(0)

    def to_json(self) -> dict:
        return {
            "shots": {k: str(v) for k, v in self.shots.items()},
            "thumbnail": str(self.thumbnail) if self.thumbnail else None,
            "portraits": {k: str(v) for k, v in self.portraits.items()},
            "cost_usd": str(self.cost_usd),
        }


def character_style(brand_dir: Path) -> str:
    """The character half of the style block: how people are drawn, without any setting."""
    return prompting.style(brand_dir)["style"]["night"].split(", set against")[0]


def full_prompt(prompt: str, negative: str, names: list[str], note: str | None) -> str:
    parts = [FRAMING, prompt.rstrip(". ") + "."]
    if note:
        parts.append(f"Director's note for this frame: {note.rstrip('. ')}.")
    if names:
        parts.append(REFERENCE_NOTE.format(names=", ".join(names)))
    parts.append(f"Avoid: {negative}.")
    return " ".join(parts)


class FrameMaker:
    def __init__(
        self,
        draw: Draw,
        ledger: Ledger,
        brand_dir: Path,
        cache_dir: Path,
        model: str,
        fallback_model: str | None = None,
    ) -> None:
        self.draw = draw
        self.ledger = ledger
        self.brand_dir = brand_dir
        self.cache_dir = cache_dir
        self.models = [m for m in (model, fallback_model) if m]
        self.cast = prompting.cast(brand_dir)
        self.spent = Decimal(0)
        self._lock = threading.Lock()

    def _references(self, character_ids: list[str], portraits: dict[str, Path]) -> list[Path]:
        refs: list[Path] = []
        for cid in character_ids:
            if cid in self.cast:
                refs += [self.brand_dir / r for r in self.cast[cid].get("references", [])]
            elif cid in portraits:
                refs.append(portraits[cid])
        return refs

    def _names(self, character_ids: list[str], board: Storyboard, refs_for: set[str]) -> list[str]:
        names = {c.id: c.name for c in board.characters}
        return [names.get(cid, cid) for cid in character_ids if cid in refs_for]

    def image(self, prompt: str, refs: list[Path], label: str, take: int = 1) -> Path:
        """One image, from the cache or paid for once; the fallback model if the first fails.

        `take` > 1 asks for a fresh drawing of the same prompt (a /reshoot without a note).
        """
        key = cache_key(self.models[0], prompt, *refs, *([f"take {take}"] if take > 1 else []))
        path = self.cache_dir / f"{key}.png"
        if path.exists():
            return path
        last: Exception | None = None
        for model in self.models:
            self.ledger.check(image_estimate(model))
            try:
                img = self.draw(prompt, model, refs)
            except MediaError as e:
                last = e
                log.warning("image failed", extra={"model": model, "frame": label, "error": str(e)})
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(img.data)
            self.ledger.record(
                "image", img.model, img.cost_usd, path, {"frame": label, "prompt": prompt[:2000]}
            )
            with self._lock:  # frames are drawn a few at a time
                self.spent += img.cost_usd
            return path
        raise MediaError(f"no image model could draw {label}: {last}")

    def _portraits(self, board: Storyboard) -> dict[str, Path]:
        seen = Counter(cid for shot in board.shots for cid in shot.characters)
        out: dict[str, Path] = {}
        style = character_style(self.brand_dir)
        for c in board.characters:
            if c.id in self.cast or seen[c.id] < 2:
                continue
            prompt = PORTRAIT.format(descriptor=c.descriptor, character_style=style)
            out[c.id] = self.image(prompt, [], f"portrait:{c.id}")
        return out

    def _scene(
        self,
        content: prompting.ImagePrompt,
        character_ids: list[str],
        board: Storyboard,
        portraits: dict[str, Path],
        note: str | None,
        label: str,
        take: int = 1,
    ) -> Path:
        refs = self._references(character_ids, portraits)
        with_refs = {
            cid
            for cid in character_ids
            if cid in portraits or self.cast.get(cid, {}).get("references")
        }
        names = self._names(character_ids, board, with_refs)
        prompt = full_prompt(content.prompt, content.negative, names, note)
        return self.image(prompt, refs, label, take)

    def make(
        self,
        board: Storyboard,
        thumbnail: Thumbnail | None = None,
        notes: dict[str, str] | None = None,
        takes: dict[str, int] | None = None,
    ) -> Frames:
        """Every shot's frame and the thumbnail. `notes`: frame id -> the owner's /reshoot note;
        `takes`: frame id -> how many times it has been drawn.

        Frames already bought come back from the cache, so a reshoot pays only for what changed.
        """
        notes, takes = notes or {}, takes or {}
        frames = Frames(portraits=self._portraits(board))  # first: shots are conditioned on them
        jobs = [
            (shot.id, prompting.image_prompt(shot, board), shot.characters) for shot in board.shots
        ]
        if thumbnail is not None:
            jobs.append(
                ("thumbnail", prompting.thumbnail_prompt(thumbnail, board), thumbnail.characters)
            )

        def draw(job):
            label, content, characters = job
            return self._scene(
                content,
                characters,
                board,
                frames.portraits,
                notes.get(label),
                label,
                takes.get(label, 1),
            )

        # a few at a time: ~15 s each, so a 13-frame episode takes about a minute, not three.
        # Concurrent budget checks can overshoot the cap by at most PARALLEL - 1 images.
        with ThreadPoolExecutor(PARALLEL) as pool:
            paths = list(pool.map(draw, jobs))
        for (label, _, _), path in zip(jobs, paths, strict=True):
            if label == "thumbnail":
                frames.thumbnail = path
            else:
                frames.shots[label] = path
        frames.cost_usd = self.spent
        return frames
