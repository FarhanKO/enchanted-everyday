"""The renderer with real ffmpeg, on a short stand-in episode (a few seconds of video)."""

from __future__ import annotations

import shutil
from decimal import Decimal
from pathlib import Path

import pytest

from engine.llm.schemas import (
    BEAT_ORDER,
    Beat,
    Line,
    Location,
    MusicCue,
    Script,
    Shot,
    Sound,
    Storyboard,
)
from engine.media import ffmpeg
from engine.media.images import FrameMaker
from engine.media.paid import CapLedger
from engine.media.render import render
from engine.media.timeline import captions, fit_shots
from engine.media.voice import VoiceMaker
from tests.fakes_media import fake_image, fake_speech

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")

BRAND = Path("brand")
CAMERAS = ("push_in", "pan_left", "tilt_up", "parallax", "pull_out", "static")


def short_episode() -> tuple[Script, Storyboard]:
    """One short line and one shot per beat. Built without validation: the real contract
    insists on 45-90 seconds, and this only needs to exercise the renderer."""
    script = Script.model_construct(
        title="t",
        narration_direction="calm",
        beats=[
            Beat.model_construct(
                name=b,
                lines=[Line.model_construct(speaker="narrator", text="Two small words.",
                                            delivery="soft", pause_after_s=0.3)],
            )
            for b in BEAT_ORDER
        ],
    )  # fmt: skip
    loc = Location.model_construct(
        id="room", name="Room", pole="night", descriptor="a small room", lighting="lamp"
    )
    shots = [
        Shot.model_construct(
            id=f"S{i + 1:02d}", beat=b, start_s=i * 1.5, duration_s=1.5, description="d",
            camera=CAMERAS[i], pole="night", location="room", characters=["fann"] if i == 1 else [],
            image_prompt=f"frame {i}", motion="still_drift", video_prompt="", overlays=[],
            sfx=["rain on glass"] if i < 3 else ["sea waves"],
        )
        for i, b in enumerate(BEAT_ORDER)
    ]  # fmt: skip
    sound = Sound.model_construct(
        music_palette="",
        cues=[MusicCue.model_construct(at_s=0, action="enter", note="")],
        ambience=[],
    )
    return script, Storyboard.model_construct(
        characters=[], locations=[loc], shots=shots, sound=sound
    )


def test_render_makes_a_vertical_video_with_sound_and_captions(tmp_path):
    script, board = short_episode()
    ledger = CapLedger(Decimal("1"))
    voice = VoiceMaker(fake_speech, ledger, BRAND, tmp_path / "cache").make(
        script, tmp_path / "v.wav"
    )
    frames = FrameMaker(fake_image, ledger, BRAND, tmp_path / "img", "m")
    shot_frames = {s.id: frames.image(s.image_prompt, [], s.id) for s in board.shots}
    shots = fit_shots(board, voice)

    result = render(
        board=board, shots=shots, frames=shot_frames, voice=voice,
        caps=captions(voice, "Goodnight, sleepless soul."), out_dir=tmp_path / "out",
        brand_dir=BRAND, music_dir=tmp_path / "no-music", seed="t", thumb_src=shot_frames["S01"],
        thumb_text="HIS LAST DREAM",
    )  # fmt: skip

    info = ffmpeg.probe(result.path)
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert (video["width"], video["height"]) == (1080, 1920)
    assert result.duration_s == pytest.approx(voice.duration_s, abs=0.1)
    qc = result.qc
    assert abs(qc["lufs"] + 14) <= 1.0 and qc["true_peak_db"] <= -0.5
    # a stand-in this short only fails the 45-90 s rule; the picture, sound and loudness pass
    assert [i for i in qc["issues"] if "Shorts here are" not in i] == []
    assert any("no music" in n for n in qc["notes"])
    assert result.preview.exists() and result.thumbnail.exists()
    assert (tmp_path / "out" / "build" / "captions.ass").read_text(encoding="utf-8").count(
        "Goodnight, sleepless soul."
    ) == 2  # the shadow and the text
