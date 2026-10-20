"""Phase 2 media, offline: the voice track, frames, timing, captions and the OpenRouter client."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import httpx
import numpy as np
import pytest

from engine.budget import BudgetExceeded
from engine.llm.schemas import Episode
from engine.media import music, synth, voice
from engine.media.ffmpeg import RATE
from engine.media.images import FrameMaker, full_prompt
from engine.media.openrouter import Image, MediaError, OpenRouterMedia
from engine.media.paid import CapLedger
from engine.media.render import captions_ass, motion, trim_paper
from engine.media.timeline import TimedShot, captions, fit_shots, phrases, wrap
from engine.media.voice import VoiceMaker, breathe, tagged, tempo_for
from tests.conftest import GOLDEN_EPISODE
from tests.fakes_media import fake_image, fake_speech

BRAND = Path("brand")


@pytest.fixture
def episode() -> Episode:
    return Episode.model_validate(json.loads(GOLDEN_EPISODE.read_text(encoding="utf-8")))


class Counting:
    def __init__(self, fn, fail_models: tuple[str, ...] = ()):
        self.fn, self.fail_models, self.calls = fn, fail_models, []

    def __call__(self, *args):
        self.calls.append(args)
        if args[1] in self.fail_models:
            raise MediaError("no", status=400)
        return self.fn(*args)


# ---------------------------------------------------------------- voice


@pytest.mark.parametrize(
    ("delivery", "spoken"),
    [
        ("hushed, like a secret", "[softly] Hi."),
        ("barely above a whisper, warm, unhurried", "[whispers] Hi."),
        ("slower on 'breathing', a touch of wonder", "[slowly] Hi."),
        ("matter-of-fact", "Hi."),
    ],
)
def test_delivery_notes_become_audio_tags(delivery, spoken):
    assert tagged("Hi.", delivery) == spoken


def test_a_slow_speaker_always_speaks_slowly():
    assert tagged("Hi.", "hushed", slow=True) == "[softly] [slowly] Hi."
    assert tagged("Hi.", "slower", slow=True) == "[slowly] Hi."  # never twice


@pytest.mark.parametrize(
    ("words", "seconds", "tempo"),
    [
        (20, 10.0, 1.0),  # 120 wpm: already the pace
        (26, 10.0, 0.8),  # 156 wpm: slowed, but never below min_tempo
        (22, 10.0, 120 / 132),  # 132 wpm: slowed just enough
        (2, 0.5, 1.0),  # too short to measure
    ],
)
def test_fast_lines_are_slowed_to_the_speakers_pace(words, seconds, tempo):
    assert tempo_for(words, seconds, 120, 0.8) == pytest.approx(tempo)


def test_sentence_breaks_last_long_enough():
    tone = (0.3 * np.sin(2 * np.pi * 220 * np.arange(RATE // 2) / RATE)).astype(np.float32)
    comma, stop = np.zeros(RATE // 10, np.float32), np.zeros(int(0.3 * RATE), np.float32)
    line = np.concatenate([tone, comma, tone, stop, tone])
    grown = (breathe(line, 0.45).size - line.size) / RATE
    assert grown == pytest.approx(0.15, abs=0.02)  # only the full stop, topped up to 0.45 s
    assert breathe(line, 0.25).size == line.size  # already long enough
    assert breathe(line, 0).size == line.size


def test_voice_slows_a_fast_speaker(tmp_path, episode):
    """The fake speaks ~156 wpm; the narrator's pace is 118, so each long line is stretched."""
    track = VoiceMaker(fake_speech, CapLedger(Decimal("1")), BRAND, tmp_path).make(
        episode.script, tmp_path / "v.wav"
    )
    long_lines = [
        line for line in track.lines if line.speaker == "narrator" and len(line.text.split()) >= 8
    ]
    assert long_lines
    for line in long_lines:
        wpm = len(line.text.split()) / (line.end_s - line.start_s) * 60
        assert wpm < 135


def test_voice_track_times_every_line_and_holds_for_the_message(tmp_path, episode):
    speak = Counting(fake_speech)
    ledger = CapLedger(Decimal("1"))
    track = VoiceMaker(speak, ledger, BRAND, tmp_path / "cache").make(
        episode.script, tmp_path / "voice.wav"
    )
    lines = episode.script.lines
    assert len(track.lines) == len(lines) and len(speak.calls) == len(lines)  # nothing after
    for a, b in zip(track.lines, track.lines[1:], strict=False):
        assert b.start_s == pytest.approx(a.end_s + a.pause_s, abs=0.01)  # the scripted pause
    assert track.lines[0].start_s == 0
    assert track.message_start_s > track.story_end_s >= track.lines[-1].end_s
    assert 3.0 <= track.message_end_s - track.message_start_s <= 4.5  # long enough to read
    assert track.duration_s - track.message_end_s == pytest.approx(voice.TAIL_S, abs=0.01)
    assert "Goodnight" not in " ".join(call[0] for call in speak.calls)
    assert ledger.spent_usd == track.cost_usd > 0


def test_voice_is_paid_for_once(tmp_path, episode):
    speak = Counting(fake_speech)
    for _ in range(2):
        ledger = CapLedger(Decimal("1"))
        VoiceMaker(speak, ledger, BRAND, tmp_path / "cache").make(
            episode.script, tmp_path / "v.wav"
        )
    assert len(speak.calls) == len(episode.script.lines)
    assert ledger.spent_usd == 0  # the second run came from the cache


def test_voice_falls_back_to_the_older_model(tmp_path, episode):
    speak = Counting(fake_speech, fail_models=("elevenlabs/eleven-v4",))
    VoiceMaker(speak, CapLedger(Decimal("1")), BRAND, tmp_path).make(
        episode.script, tmp_path / "v.wav"
    )
    assert {c[1] for c in speak.calls} == {"elevenlabs/eleven-v4", "elevenlabs/eleven-v3"}


def test_voice_stops_at_the_cap(tmp_path, episode):
    with pytest.raises(BudgetExceeded):
        VoiceMaker(fake_speech, CapLedger(Decimal("0.001")), BRAND, tmp_path).make(
            episode.script, tmp_path / "v.wav"
        )


# ---------------------------------------------------------------- frames


def _frames(tmp_path, draw=fake_image, cap="5"):
    ledger = CapLedger(Decimal(cap))
    maker = FrameMaker(draw, ledger, BRAND, tmp_path, "google/gemini-nano-banana-2.1", "nb2")
    return maker, ledger


def test_every_shot_and_the_cover_get_a_frame(tmp_path, episode):
    draw = Counting(fake_image)
    maker, ledger = _frames(tmp_path, draw)
    frames = maker.make(episode.storyboard, episode.package.thumbnail)
    assert list(frames.shots) == [s.id for s in episode.storyboard.shots]
    assert frames.thumbnail is not None and frames.portraits == {}  # no repeat supporting cast
    assert len(draw.calls) == len(episode.storyboard.shots) + 1
    assert ledger.spent_usd == Decimal("0.04") * len(draw.calls)


def test_cast_members_are_conditioned_on_their_references(tmp_path, episode):
    draw = Counting(fake_image)
    _frames(tmp_path, draw)[0].make(episode.storyboard)
    by_frame = {  # drawn in parallel, so match calls to shots by their prompt
        s.id: next(c for c in draw.calls if s.image_prompt.rstrip(". ") in c[0])
        for s in episode.storyboard.shots
    }
    prompt, _, refs = by_frame["S02"]  # Fann alone
    assert [r.name for r in refs] == ["portrait_v1.jpg"]  # never the labelled draft sheet
    assert "approved reference art for Fann" in prompt
    assert "mustard-yellow knitted scarf" in prompt  # the locked descriptor, verbatim
    assert by_frame["S04"][2] == []  # the Shopkeeper has no approved reference yet
    assert "reference art" not in by_frame["S04"][0]


def test_a_reshoot_note_and_take_redraw_only_that_frame(tmp_path, episode):
    draw = Counting(fake_image)
    maker, _ = _frames(tmp_path, draw)
    first = maker.make(episode.storyboard)
    n = len(draw.calls)
    again = maker.make(episode.storyboard, notes={"S03": "warmer light"}, takes={"S03": 2})
    assert (
        len(draw.calls) == n + 1
        and "Director's note for this frame: warmer light." in (draw.calls[-1][0])
    )
    assert again.shots["S03"] != first.shots["S03"]
    assert again.shots["S02"] == first.shots["S02"]
    maker.make(episode.storyboard, takes={"S05": 2})  # no note: drawn again all the same
    assert len(draw.calls) == n + 2


def test_frames_fall_back_to_the_second_model(tmp_path, episode):
    draw = Counting(fake_image, fail_models=("google/gemini-nano-banana-2.1",))
    board = episode.storyboard.model_copy(update={"shots": episode.storyboard.shots[:1]})
    _frames(tmp_path, draw)[0].make(board)
    assert [c[1] for c in draw.calls] == ["google/gemini-nano-banana-2.1", "nb2"]


def test_full_prompt_order():
    p = full_prompt("Fann at the door", "text, watermark", ["Fann"], None)
    assert p.startswith("A single vertical 9:16 illustration")
    assert p.index("Fann at the door") < p.index("reference art") < p.index("Avoid: text")


# ---------------------------------------------------------------- timing and captions


@pytest.fixture
def track(tmp_path, episode):
    return VoiceMaker(fake_speech, CapLedger(Decimal("1")), BRAND, tmp_path).make(
        episode.script, tmp_path / "v.wav"
    )


def test_shots_tile_the_voice_track_beat_by_beat(track, episode):
    shots = fit_shots(episode.storyboard, track)
    assert [s.id for s in shots] == [s.id for s in episode.storyboard.shots]
    assert shots[0].start_s == 0 and shots[-1].end_s == pytest.approx(track.duration_s, abs=1e-3)
    for a, b in zip(shots, shots[1:], strict=False):
        assert a.end_s == pytest.approx(b.start_s, abs=1e-3)
    reveal = [line for line in track.lines if line.beat == "reveal"]
    first_reveal_shot = next(
        t for t, s in zip(shots, episode.storyboard.shots, strict=True) if s.beat == "reveal"
    )
    assert first_reveal_shot.start_s == pytest.approx(
        track.lines[track.lines.index(reveal[0]) - 1].end_s
        + track.lines[track.lines.index(reveal[0]) - 1].pause_s,
        abs=1e-3,
    )
    # the bell and the signature hold on the last shot alone: the final line plays over the
    # final image, not over the shot before it
    assert shots[-1].start_s <= track.lines[-1].start_s + 0.5
    # inside a beat, the picture changes in the gap between lines, never mid-line
    beat_of = {s.id: s.beat for s in episode.storyboard.shots}
    cost = [s for s in shots if beat_of[s.id] == "cost"]
    line_ends = {round(line.end_s, 3) for line in track.lines if line.beat == "cost"}
    assert len(cost) > 1 and all(round(s.end_s, 3) in line_ends for s in cost[:-1])


@pytest.mark.parametrize(
    ("text", "chunks"),
    [
        ("Fann sold his first dream at midnight.", ["Fann sold his first dream", "at midnight."]),
        ("Then she asked for the last one.", ["Then she asked", "for the last one."]),
        (
            '"This one," she said, "pays for everything."',
            ['"This one," she said,', '"pays for everything."'],
        ),
        ("And smiling.", ["And smiling."]),
    ],
)
def test_captions_break_at_natural_phrases(text, chunks):
    assert [" ".join(c) for c in phrases(text)] == chunks


def test_caption_lines_are_short_and_even():
    words = ["Letters", "he", "was", "afraid", "to", "open."]
    assert wrap(words) == ["Letters he was", "afraid to open."]
    assert wrap(list("abcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyz")) is None


def test_captions_follow_the_voice(track):
    caps = captions(track, "Some dreams are too old to sell.")
    *spoken, message = caps
    assert message.message and not any(c.message for c in spoken)
    assert message.lines == ["Some dreams are too old", "to sell."]
    assert message.start_s == pytest.approx(track.message_start_s)
    for c in spoken:
        assert 2 <= sum(len(line.split()) for line in c.lines) <= 6 or len(c.lines[0].split()) <= 2
        assert all(len(line) <= 26 for line in c.lines) and len(c.lines) <= 2
    for a, b in zip(caps, caps[1:], strict=False):
        assert a.end_s <= b.start_s + 1e-6


def test_caption_file_is_calm_and_in_the_safe_zone():
    from engine.media.timeline import Caption

    ass = captions_ass([Caption(1.0, 2.5, ["Fann sold his", "first dream"])])
    assert "Lora" in ass and "\\fad(150,150)" in ass and "\\pos(540,1382)" in ass
    assert "0:00:01.00,0:00:02.50" in ass and "Fann sold his\\Nfirst dream" in ass


@pytest.mark.parametrize(
    "camera", ["push_in", "pull_out", "pan_left", "tilt_up", "parallax", "static"]
)
def test_every_camera_move_has_a_motion(camera):
    assert motion(camera, 90).startswith("z='")


# ---------------------------------------------------------------- sound


def test_signature_sounds_are_ours_and_audible():
    for make in (synth.fann_motif, synth.tina_motif, synth.dupatta_rustle):
        sound = make()
        assert sound.size > 0 and 0.2 < float(abs(sound).max()) <= 1.0
    assert synth.bed_kind(["rain on the window"]) == "rain"
    assert synth.bed_kind(["sea waves", "wind"]) == "sea"
    assert synth.bed_kind(["clock tick"]) == "room"


def test_music_needs_a_license(tmp_path):
    (tmp_path / "a.mp3").write_bytes(b"x")
    (tmp_path / "b.mp3").write_bytes(b"x")
    (tmp_path / "library.toml").write_text(
        '[[track]]\nfile = "a.mp3"\nmoods = ["calm", "sparkly"]\nlicense = "CC BY 4.0"\n'
        '[[track]]\nfile = "b.mp3"\nmoods = ["calm"]\n',
        encoding="utf-8",
    )
    tracks = music.library(tmp_path)
    assert [t.path.name for t in tracks] == ["a.mp3"]
    assert tracks[0].moods == ("calm",)  # an unknown mood is dropped
    assert music.library(tmp_path / "missing") == []


def test_the_music_library_covers_every_mood():
    import tomllib

    text = Path("templates/music/library.toml").read_text(encoding="utf-8")
    entries = tomllib.loads(text)["track"]
    for mood in music.MOODS:
        assert sum(mood in e["moods"] for e in entries) >= 2, mood
    for e in entries:
        assert e["license"] and e["credit"].startswith("Music: "), e["file"]
        assert set(e["moods"]) <= set(music.MOODS), e["file"]


def _board_with_moods(episode, moods):
    shots = [
        s.model_copy(update={"music": m})
        for s, m in zip(episode.storyboard.shots, moods, strict=False)
    ]
    return episode.storyboard.model_copy(update={"shots": shots})


def _timed(board, seconds):
    out, t = [], 0.0
    for shot, length in zip(board.shots, seconds, strict=False):
        out.append(TimedShot(shot.id, t, t + length))
        t += length
    return out


def test_music_sections_follow_the_moods_and_fold_short_runs(episode):
    n = len(episode.storyboard.shots)
    moods = ["calm"] * 3 + ["mystery"] + ["tension"] * 4 + ["warm"] * (n - 8)
    board = _board_with_moods(episode, moods)
    secs = music.sections(board, _timed(board, [6] * n))
    # the lone 6 s mystery shot is too short for its own track: it joins the calm run
    assert [s.mood for s in secs] == ["calm", "tension", "warm"]
    assert secs[0].start_s == 0 and secs[0].end_s == 24
    assert all(a.end_s == b.start_s for a, b in zip(secs, secs[1:], strict=False))


def _track(name, moods, pole="any"):
    return music.Track(Path(name), name, tuple(moods), pole, "CC BY 4.0", f"Music: {name}")


def test_music_is_relevant_and_varies_between_episodes():
    tracks = [
        _track("calm_a", ["calm"]),
        _track("calm_b", ["calm"]),
        _track("both", ["tension", "calm"]),
        _track("tense", ["tension"]),
    ]
    secs = [
        music.Section("calm", 0, 20, "night"),
        music.Section("tension", 20, 50, "night"),
        music.Section("none", 50, 60, "night"),
    ]
    first = music.choose(secs, tracks, recent=[], seed="ep1")
    assert first[0].track.moods[0] == "calm"  # a track whose strongest mood it is
    assert first[1].track.path.name == "tense"
    assert first[2].track is None  # silence where the storyboard asks for none
    heard = [c.track.path.name for c in first if c.track]
    second = music.choose(secs, tracks, recent=heard, seed="ep2")
    assert second[0].track.path.name not in heard  # the next episode sounds different
    assert second[1].track.path.name == "both"  # tension too, from its second-choice track
    assert music.credits(first) == [f"Music: {n}" for n in heard]


def test_the_owners_preferred_sound_comes_first_while_fresh():
    plain = _track("plain", ["calm"])
    liked = music.Track(
        Path("liked"), "liked", ("calm", "sorrow"), "any", "CC BY 4.0", "", 0.0, True
    )
    secs = [music.Section("calm", 0, 20, "night")]
    # preferred even though calm is only its first mood too, and whatever the seed
    for seed in ("a", "b", "c"):
        assert music.choose(secs, [plain, liked], recent=[], seed=seed)[0].track is liked
    # but never at the cost of repeating what the last episodes played
    assert music.choose(secs, [plain, liked], recent=["liked"], seed="a")[0].track is plain


def test_music_bed_crossfades_sections_and_ducks_under_the_voice(episode):
    n = len(episode.storyboard.shots)
    board = _board_with_moods(episode, ["calm"] * 4 + ["none"] * 4 + ["warm"] * (n - 8))
    timed = _timed(board, [5] * n)
    total = int(timed[-1].end_s * RATE)
    voice = np.zeros(total, np.float32)
    voice[10 * RATE : 12 * RATE] = 0.3  # someone speaks from 10 to 12 s
    cues = music.choose(
        music.sections(board, timed), [_track("c", ["calm"]), _track("w", ["warm"])], [], "s"
    )
    tone = (0.2 * np.sin(2 * np.pi * 330 * np.arange(10 * RATE) / RATE)).astype(np.float32)
    bed = music.bed(
        cues,
        board.model_copy(update={"sound": board.sound.model_copy(update={"cues": []})}),
        timed,
        voice,
        decode=lambda path: tone,
    )

    def rms(a, b):
        return float(np.sqrt(np.mean(bed[int(a * RATE) : int(b * RATE)] ** 2)))

    assert rms(23, 37) < 1e-4  # the none section is silent (its edges crossfade)
    assert rms(14, 18) > 0.05 and rms(45, 50) > 0.05
    assert rms(10.5, 11.5) < rms(14, 15) * 0.7  # ducked under the voice
    assert rms(timed[-1].end_s - 0.2, timed[-1].end_s) < 0.01  # faded out under the ending


def test_posted_copy_credits_the_music(episode):
    from engine.approval import post_copy, posting_kit

    credit = 'Music: "Moonlight" by Scott Buckley – released under CC-BY 4.0.'
    text = post_copy("A story.", ["#fairytale"], [credit])
    assert text == f"A story.\n\n{credit}\n\n#fairytale"
    kit = posting_kit(episode, [credit])
    assert sum(credit in m for m in kit) == 4  # YouTube, Instagram, Facebook, TikTok


# ---------------------------------------------------------------- OpenRouter


def test_image_request_and_cost():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(
            200,
            json={
                "model": "google/gemini-nano-banana-2.1",
                "choices": [
                    {"message": {"images": [{"image_url": {"url": "data:image/png;base64,iVBO"}}]}}
                ],
                "usage": {"cost": 0.0405},
            },
        )

    client = OpenRouterMedia("sk-test", httpx.Client(transport=httpx.MockTransport(handler)))
    img = client.image(
        "a tree",
        "google/gemini-nano-banana-2.1",
        [GOLDEN_EPISODE.parents[2] / "brand/references/fann/portrait_v1.jpg"],
    )
    assert isinstance(img, Image) and img.cost_usd == Decimal("0.0405") and img.mime == "image/png"
    assert seen["auth"] == "Bearer sk-test"
    assert (
        seen["modalities"] == ["image", "text"] and seen["image_config"]["aspect_ratio"] == "9:16"
    )
    content = seen["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "a tree"}
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_a_refusal_in_words_is_an_error():
    def handler(request):
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "I can't draw that."}}]}
        )

    client = OpenRouterMedia("k", httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(MediaError, match="returned no image: I can't draw that"):
        client.image("x", "m")


def test_speech_errors_carry_the_status_not_the_key():
    def handler(request):
        return httpx.Response(402, text="insufficient credits")

    client = OpenRouterMedia("sk-secret", httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(MediaError) as e:
        client.speech("hi", "elevenlabs/eleven-v4", "brian")
    assert e.value.status == 402 and "sk-secret" not in str(e.value)


def test_a_painted_paper_border_is_trimmed():
    from PIL import Image as PILImage

    art = PILImage.new("RGB", (600, 1000), (40, 50, 90))
    framed = PILImage.new("RGB", (680, 1100), (246, 242, 232))  # cream paper around the art
    framed.paste(art, (40, 50))
    w, h = trim_paper(framed).size
    assert w <= 600 and h <= 1000  # the paper is gone, and a little more for its ragged edge
    assert w >= 540 and h >= 900
    assert trim_paper(art).size == art.size  # full-bleed art is left alone
