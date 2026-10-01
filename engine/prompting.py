"""Assemble final image/video prompts from an agent's shot text plus the brand's locked fragments.

Agents write only what is specific to a shot. Everything that must stay identical across frames
(character descriptors, locations, the style block, the negative prompt) is appended here, verbatim.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from engine.llm.schemas import Shot, Storyboard, Thumbnail

BRAND_DIR = Path(__file__).resolve().parent.parent / "brand"


@dataclass(frozen=True)
class ImagePrompt:
    prompt: str
    negative: str


@lru_cache
def style(brand_dir: Path = BRAND_DIR) -> dict:
    with open(brand_dir / "style.toml", "rb") as f:
        return tomllib.load(f)


def _scene(
    content: str, pole: str, location_id: str, character_ids: list[str], board: Storyboard
) -> ImagePrompt:
    s = style()
    chars = {c.id: c for c in board.characters}
    loc = next(loc for loc in board.locations if loc.id == location_id)
    parts = [content.rstrip(". ")]
    parts += [chars[cid].descriptor for cid in character_ids]
    parts += [f"Setting: {loc.descriptor}", f"Lighting: {loc.lighting}", s["style"][pole]]
    return ImagePrompt(prompt=". ".join(parts), negative=s["style"]["negative"])


def image_prompt(shot: Shot, board: Storyboard) -> ImagePrompt:
    return _scene(shot.image_prompt, shot.pole, shot.location, shot.characters, board)


def thumbnail_prompt(thumb: Thumbnail, board: Storyboard) -> ImagePrompt:
    return _scene(thumb.image_prompt, thumb.pole, thumb.location, thumb.characters, board)


def video_prompt(shot: Shot) -> str:
    s = style()
    camera, suffix = s["camera"][shot.camera], s["style"]["video_suffix"]
    return f"{camera}. {shot.video_prompt.rstrip('. ')}. {suffix}"
