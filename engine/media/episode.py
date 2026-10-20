"""One episode, from contract to video: voice, frames, timing, render.

The pipeline stages (engine/stages/media.py) run these steps one at a time, so a failure resumes
where it stopped; `engine render` runs them all on an episode.json, with no database.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from engine.config import Settings
from engine.llm.schemas import Episode
from engine.media.images import FrameMaker, Frames
from engine.media.openrouter import OpenRouterMedia
from engine.media.paid import Ledger
from engine.media.render import RenderResult, render
from engine.media.timeline import captions, fit_shots
from engine.media.voice import VoiceMaker, VoiceTrack


@dataclass
class Makers:
    voice: VoiceMaker
    frames: FrameMaker


def makers(settings: Settings, ledger: Ledger, client: OpenRouterMedia | None = None) -> Makers:
    if client is None:
        if not settings.openrouter_api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not set; images and voice go through it")
        client = OpenRouterMedia(settings.openrouter_api_key.get_secret_value())
    brand = Path(settings.brand_dir)
    cache = Path(settings.work_dir) / "cache"
    return Makers(
        voice=VoiceMaker(client.speech, ledger, brand, cache / "voice"),
        frames=FrameMaker(
            lambda prompt, model, refs: client.image(prompt, model, refs),
            ledger,
            brand,
            cache / "images",
            settings.image_model,
            settings.image_fallback_model,
        ),
    )


def render_episode(
    ep: Episode,
    voice: VoiceTrack,
    frames: Frames,
    out_dir: Path,
    settings: Settings,
    recent_music: Sequence[str] = (),
) -> RenderResult:
    """`recent_music`: track files heard in earlier episodes, most recent first, so this one
    sounds different."""
    brand = Path(settings.brand_dir)
    shots = fit_shots(ep.storyboard, voice)
    caps = captions(voice, ep.script.closing_line)
    return render(
        board=ep.storyboard,
        shots=shots,
        frames=frames.shots,
        voice=voice,
        caps=caps,
        out_dir=out_dir,
        brand_dir=brand,
        music_dir=Path(settings.music_dir),
        seed=ep.id,
        recent_music=recent_music,
        thumb_src=frames.thumbnail,
        thumb_text=ep.package.thumbnail.text,
        fps=settings.render_fps,
        crf=settings.render_crf,
    )


def produce_episode(
    ep: Episode,
    out_dir: Path,
    settings: Settings,
    m: Makers,
    notes: dict[str, str] | None = None,
    takes: dict[str, int] | None = None,
    recent_music: Sequence[str] = (),
) -> tuple[VoiceTrack, Frames, RenderResult]:
    out_dir.mkdir(parents=True, exist_ok=True)
    voice = m.voice.make(ep.script, out_dir / "voice.wav")
    frames = m.frames.make(ep.storyboard, ep.package.thumbnail, notes, takes)
    return voice, frames, render_episode(ep, voice, frames, out_dir, settings, recent_music)
