"""Render: frames, voice and sound into the finished 1080x1920 video, then QC.

Picture, in one ffmpeg pass: each frame drifts slowly (push-in, pull-back, pan, tilt or parallax,
as the shot's camera says, 4-8%), shots crossfade, a faint film grain and vignette sit over
everything, and the captions are burned in (Lora SemiBold, warm cream, soft shadow). It opens out of
black and closes into the storyboard's fade_out: black, white, glow or sunray.

Sound, mixed here: the voice; one ambience bed per shot from its sfx (rain, sea, wind or room
tone), crossfaded; each recurring character's sound where they first appear; the moon bell before
the signature line; and the music, a licensed track for each stretch of the story matched to its
mood (engine/media/music.py), ducked under the voice. Then loudness-normalised in two passes to
-14 LUFS, -1 dBTP.

`ai_clip` shots are drawn as still frames with drift until AI video is switched on.
"""

from __future__ import annotations

import json
import logging
import re
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from engine.llm.schemas import Storyboard
from engine.media import ffmpeg, music, synth
from engine.media.ffmpeg import RATE
from engine.media.timeline import Caption, TimedShot
from engine.media.voice import VoiceTrack

log = logging.getLogger(__name__)

W, H = 1080, 1920
WORK_SCALE = 2  # frames are prepared at 2x so slow zooms move in sub-pixel steps
FADE_S = 0.8
FADE_IN_S = 1.0  # every episode opens out of black
FADE_OUT_S = 1.6  # and closes into its fade_out colour
LIGHT_S = 2.5  # glow and sunray: the light builds this long before the colour takes over
FADE_COLOURS = {"black": "black", "white": "white", "glow": "0xFFE3B0", "sunray": "0xFFF3DA"}
LUFS, TRUE_PEAK = -14.0, -1.0

# levels, linear, before loudness normalisation. Speech sits near 0.075 RMS; music is levelled
# to 0.1 RMS (music.TARGET_RMS). Measured on the pilot: the music sits ~17 dB under a speaking
# voice (ducked) and ~13 dB under it in the pauses, the ambience ~23 dB under: mild, but there
# (Farhan, 2026-10-12)
VOICE_GAIN = 1.0
MUSIC_GAIN = 0.3
BED_GAIN = 0.05
PRESENCE_GAIN = 0.35
BELL_GAIN = 0.45

# #F6EEDF; #1A1530 at ~70% (ASS colours are &HAABBGGRR). The shadow is a soft halo: the same
# text widened and blurred, so captions read over a glowing jar without a box or a hard outline.
CREAM, SHADOW = "&H00DFEEF6", "&H4D30151A"
CAPTION_Y = int(H * 0.72)


@dataclass
class RenderResult:
    path: Path
    preview: Path
    thumbnail: Path | None
    duration_s: float
    qc: dict = field(default_factory=dict)


# ---------------------------------------------------------------- picture


def trim_paper(img: Image.Image, extra: float = 0.03) -> Image.Image:
    """Cut the painted-paper border some drawings come with (pale, flat rows or columns at an
    edge), plus a little more on that side, since a border's inner edge is ragged."""
    a = np.asarray(img.convert("L"), dtype=np.float32)
    h, w = a.shape

    def run(lines: np.ndarray, limit: int) -> int:
        """Edge rows (or columns) that are mostly bare paper: over 40% near-white."""
        n = 0
        for line in lines[:limit]:
            if np.mean(line > 222) <= 0.4:
                break
            n += 1
        return n

    def cut(lines: np.ndarray, size: int) -> int:
        n = run(lines, int(size * 0.12))
        return n + int(size * extra) if n else 0

    box = (cut(a.T, w), cut(a, h), w - cut(a.T[::-1], w), h - cut(a[::-1], h))
    return img.crop(box) if box != (0, 0, w, h) else img


def prepare_frame(src: Path, dest: Path, scale: int = WORK_SCALE) -> Path:
    """Trim any paper border, cover-crop to 9:16 and upscale for the drift (the model draws ~1K;
    LANCZOS is kind to painterly art)."""
    w, h = W * scale, H * scale
    with Image.open(src) as img:
        img = trim_paper(img.convert("RGB"))
        ratio = max(w / img.width, h / img.height)
        img = img.resize((round(img.width * ratio), round(img.height * ratio)), Image.LANCZOS)
        left, top = (img.width - w) // 2, (img.height - h) // 2
        img.crop((left, top, left + w, top + h)).save(dest, quality=93)
    return dest


def motion(camera: str, frames: int) -> str:
    """zoompan expressions for a camera move over `frames` frames (p runs 0 -> 1)."""
    p = f"(on/{max(frames - 1, 1)})"
    cx, cy = "(iw-iw/zoom)/2", "(ih-ih/zoom)/2"
    z, x, y = "1.0", cx, cy
    if camera == "push_in":
        z = f"1.0+0.07*{p}"
    elif camera == "pull_out":
        z = f"1.07-0.07*{p}"
    elif camera in ("pan_left", "pan_right"):
        z = "1.08"
        x = f"(iw-iw/zoom)*{'(1-' + p + ')' if camera == 'pan_left' else p}"
    elif camera in ("tilt_up", "tilt_down"):
        z = "1.08"
        y = f"(ih-ih/zoom)*{'(1-' + p + ')' if camera == 'tilt_up' else p}"
    elif camera == "parallax":
        z = f"1.04+0.03*{p}"
        x = f"(iw-iw/zoom)*(0.3+0.4*{p})"
    else:  # static: a barely-there breath, so the frame never looks frozen
        z = f"1.02+0.01*{p}"
    return f"z='{z}':x='{x}':y='{y}'"


def ass_time(t: float) -> str:
    cs = round(t * 100)
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def ass_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")")


def captions_ass(caps: list[Caption], font: str = "Lora") -> str:
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, \
Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, \
Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{font},64,{CREAM},{CREAM},{CREAM},{CREAM},600,0,0,0,100,100,0,0,1,0,0,2,60,60,0,1
Style: Shadow,{font},64,{SHADOW},{SHADOW},{SHADOW},{SHADOW},600,0,0,0,100,100,0,0,1,5,0,2,60,60,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    for cap in caps:
        text = r"\N".join(ass_escape(line) for line in cap.lines)
        start, end = ass_time(cap.start_s), ass_time(cap.end_s)
        # a blurred dark copy just below, then the crisp cream text on top
        events.append(
            f"Dialogue: 0,{start},{end},Shadow,,0,0,0,,"
            f"{{\\pos({W // 2},{CAPTION_Y + 3})\\blur10\\fad(150,150)}}{text}"
        )
        events.append(
            f"Dialogue: 1,{start},{end},Caption,,0,0,0,,"
            f"{{\\pos({W // 2},{CAPTION_Y})\\fad(150,150)}}{text}"
        )
    return head + "\n".join(events) + "\n"


def sun_rays(dest: Path) -> Path:
    """Shafts of warm sunlight from just off the top-left corner, on black (black adds nothing in
    a screen blend), for the sunray fade-out."""
    sx, sy = -W * 0.15, -H * 0.08
    y, x = np.mgrid[0:H, 0:W].astype(np.float32)
    dist = np.hypot(x - sx, y - sy)
    angle = np.degrees(np.arctan2(y - sy, x - sx))
    # (direction in degrees, half-width, strength): a few uneven shafts fanning down and right
    shafts = ((30, 2.5, 0.8), (41, 1.6, 0.55), (52, 3.2, 0.9), (64, 2.0, 0.6), (77, 2.8, 0.5))
    light = sum(k * np.exp(-(((angle - a) / w) ** 2)) for a, w, k in shafts)
    light = light * np.clip(1 - dist / (H * 1.4), 0, 1) + np.exp(-((dist / (W * 0.45)) ** 2))
    rgb = np.clip(light, 0, 1)[..., None] * np.array([255, 228, 172], np.float32)
    Image.fromarray(rgb.astype(np.uint8)).filter(ImageFilter.GaussianBlur(24)).save(dest)
    return dest


def fades(src: str, fade_out: str, end_s: float, light: str | None = None) -> list[str]:
    """Open out of black; close into fade_out. glow blooms the picture's own light and sunray
    screens shafts of sun (`light`, a looped sun_rays input) over it, both building for LIGHT_S
    before the warm colour takes over."""
    parts, last = [], src
    if fade_out in ("glow", "sunray"):
        rise = max(FADE_IN_S, end_s - LIGHT_S)
        # a screen blend, A + B - A*B/255, eased in over the last LIGHT_S
        expr = f"A+(B-A*B/255)*clip((T-{rise:.3f})/{LIGHT_S:.3f},0,1)"
        if fade_out == "glow":
            parts += [f"[{last}]format=gbrp,split[base][bloom]", "[bloom]gblur=sigma=40[soft]"]
        else:
            parts += [f"[{last}]format=gbrp[base]", f"[{light}]format=gbrp,setsar=1[soft]"]
        parts.append(f"[base][soft]blend=all_expr='{expr}':shortest=1[lit]")
        last = "lit"
    out_at = max(FADE_IN_S, end_s - FADE_OUT_S)
    parts.append(
        f"[{last}]fade=t=in:st=0:d={FADE_IN_S}:color=black,"
        f"fade=t=out:st={out_at:.3f}:d={FADE_OUT_S}:color={FADE_COLOURS[fade_out]},"
        f"format=yuv420p[out]"
    )
    return parts


def picture_filter(
    shots: list[TimedShot],
    cameras: dict[str, str],
    fps: int,
    ass: Path,
    fade_out: str = "black",
    end_s: float | None = None,
    light: str | None = None,
) -> str:
    fade = min(FADE_S, min(s.duration_s for s in shots) / 2.5)
    parts = []
    for i, shot in enumerate(shots):
        length = shot.duration_s + (fade if i < len(shots) - 1 else 0)
        frames = max(2, round(length * fps))
        parts.append(
            f"[{i}:v]zoompan={motion(cameras[shot.id], frames)}:d={frames}:s={W}x{H}:fps={fps},"
            f"setsar=1,format=yuv420p[v{i}]"
        )
    last = "v0"
    for i in range(1, len(shots)):
        out = f"x{i}"
        parts.append(
            f"[{last}][v{i}]xfade=transition=fade:duration={fade:.3f}:"
            f"offset={shots[i].start_s:.3f}[{out}]"
        )
        last = out
    fonts = ffmpeg.filter_path(fonts_dir())
    parts.append(
        f"[{last}]noise=alls=3:allf=t,vignette=angle=PI/5,"
        f"ass=filename='{ffmpeg.filter_path(ass)}':fontsdir='{fonts}',format=yuv420p[pic]"
    )
    end = shots[-1].end_s if end_s is None else end_s
    parts += fades("pic", fade_out, end, light)
    return ";".join(parts)


def fonts_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "templates" / "fonts"


# ---------------------------------------------------------------- sound


def _place(mix: np.ndarray, sound: np.ndarray, at_s: float, gain: float) -> None:
    i = max(0, int(at_s * RATE))
    n = min(sound.size, mix.size - i)
    if n > 0:
        mix[i : i + n] += sound[:n] * gain


def _fade(n: int, rising: bool) -> np.ndarray:
    ramp = np.sin(np.linspace(0, np.pi / 2, max(n, 1), dtype=np.float32)) ** 2
    return ramp if rising else ramp[::-1]


def beds(shots: list[TimedShot], board: Storyboard, total: int) -> np.ndarray:
    by_id = {s.id: s for s in board.shots}
    kinds = [synth.bed_kind([*by_id[t.id].sfx, *by_id[t.id].overlays]) for t in shots]
    made = {k: synth.bed(k, total / RATE + 1) for k in set(kinds)}
    out = np.zeros(total, np.float32)
    xf = int(FADE_S * RATE)
    for shot, kind in zip(shots, kinds, strict=True):
        a, b = int(shot.start_s * RATE), min(total, int(shot.end_s * RATE) + xf)
        seg = made[kind][a:b].copy()
        k = min(xf, seg.size // 2)
        if k:
            seg[:k] *= _fade(k, True)
            seg[-k:] *= _fade(k, False)
        out[a : a + seg.size] += seg
    return out


def presences(
    shots: list[TimedShot], board: Storyboard, brand_dir: Path
) -> list[tuple[float, str]]:
    """(time, sound id): each recurring character's sound where they first appear, and again in
    any later shot whose sfx names it (a tune lost, then found)."""
    with open(brand_dir / "sound.toml", "rb") as f:
        chars = tomllib.load(f).get("characters", {})
    sounds = {c["presence"] for c in chars.values()}
    by_id = {s.id: s for s in board.shots}
    out, seen = [], set()
    for t in shots:
        shot = by_id[t.id]
        here = {s for s in shot.sfx if s in sounds}
        for cid in shot.characters:
            if cid in chars and cid not in seen:
                seen.add(cid)
                here.add(chars[cid]["presence"])
        out += [(t.start_s + 0.4, s) for s in sorted(here)]
    return out


def mix_audio(
    voice: VoiceTrack,
    board: Storyboard,
    shots: list[TimedShot],
    brand_dir: Path,
    cues: Sequence[music.Cue] = (),
) -> np.ndarray:
    v = ffmpeg.read_wav(voice.path)
    mix = v * VOICE_GAIN + beds(shots, board, v.size) * BED_GAIN
    for at, sound_id in presences(shots, board, brand_dir):
        _place(mix, synth.PRESENCE[sound_id](), at, PRESENCE_GAIN)
    _place(mix, synth.moon_bell(), voice.bell_at_s, BELL_GAIN)
    if any(c.track is not None for c in cues):
        mix += music.bed(cues, board, shots, v) * MUSIC_GAIN
    return mix


def loudness(path: Path) -> dict:
    """ffmpeg's loudnorm measurement of a file: input_i, input_tp, input_lra, input_thresh."""
    err = ffmpeg.run(
        ["-i", str(path), "-af", f"loudnorm=I={LUFS}:TP={TRUE_PEAK}:LRA=11:print_format=json",
         "-f", "null", "-"]
    )  # fmt: skip
    return json.loads(err[err.rindex("{") : err.rindex("}") + 1])


def normalise(src: Path, dest: Path) -> dict:
    m = loudness(src)
    ffmpeg.run(
        ["-loglevel", "error", "-i", str(src), "-af",
         f"loudnorm=I={LUFS}:TP={TRUE_PEAK}:LRA=11:measured_I={m['input_i']}:"
         f"measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
         f"measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true",
         "-ar", str(RATE), "-c:a", "pcm_s16le", str(dest)]
    )  # fmt: skip
    return m


# ---------------------------------------------------------------- thumbnail


def thumbnail(src: Path, text: str, dest: Path) -> Path:
    """The cover: the thumbnail frame, with its 0-4 words in Lora below the top safe zone."""
    with Image.open(src) as img:
        img = img.convert("RGB")
        ratio = max(W / img.width, H / img.height)
        img = img.resize((round(img.width * ratio), round(img.height * ratio)), Image.LANCZOS)
        left, top = (img.width - W) // 2, (img.height - H) // 2
        img = img.crop((left, top, left + W, top + H))
    if text.strip():
        font = ImageFont.truetype(str(fonts_dir() / "Lora[wght].ttf"), 104)
        font.set_variation_by_axes([600])
        words = text.upper().split()
        lines = [" ".join(words[: (len(words) + 1) // 2]), " ".join(words[(len(words) + 1) // 2 :])]
        lines = [line for line in lines if line]
        shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        y = int(H * 0.15)
        for line in lines:
            w = ImageDraw.Draw(layer).textlength(line, font=font)
            ImageDraw.Draw(shadow).text(
                ((W - w) / 2, y + 5), line, font=font, fill=(26, 21, 48, 170)
            )
            ImageDraw.Draw(layer).text(((W - w) / 2, y), line, font=font, fill=(246, 238, 223, 255))
            y += 128
        img = img.convert("RGBA")
        img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(8)))
        img.alpha_composite(layer)
        img = img.convert("RGB")
    img.save(dest, quality=92)
    return dest


# ---------------------------------------------------------------- QC


def music_notes(cues: Sequence[music.Cue], library_empty: bool) -> list[str]:
    if library_empty:
        return ["no music: add licensed tracks to templates/music (see its README)"]
    if not any(c.track is not None for c in cues):
        return ["no music: the storyboard keeps this episode to voice and ambience"]
    missing = sorted({c.section.mood for c in cues if c.track is None and c.section.mood != "none"})
    return [f"no music track for mood {m}: add one to templates/music" for m in missing]


def qc(path: Path, expect_s: float, notes: Sequence[str], ai_clips_as_stills: int) -> dict:
    info = ffmpeg.probe(path)
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    audio = [s for s in info["streams"] if s["codec_type"] == "audio"]
    dur = float(info["format"]["duration"])
    m = loudness(path)
    err = ffmpeg.run(
        ["-i", str(path), "-vf", "blackdetect=d=0.5:pix_th=0.06", "-an", "-f", "null", "-"]
    )
    # the fade in from black and a fade out to black are meant; flag only black inside the story
    blacks = [
        start
        for start, end in re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", err)
        if float(end) > FADE_IN_S + 0.5 and float(start) < expect_s - FADE_OUT_S - 0.5
    ]

    issues = []
    if (int(video["width"]), int(video["height"])) != (W, H):
        issues.append(f"resolution {video['width']}x{video['height']}, expected {W}x{H}")
    if not audio:
        issues.append("no audio stream")
    if abs(dur - expect_s) > 0.5:
        issues.append(f"runs {dur:.1f}s; the voice track is {expect_s:.1f}s")
    if not 45 <= dur <= 95:
        issues.append(f"runs {dur:.1f}s; Shorts here are 45-90s plus the ending")
    if abs(float(m["input_i"]) - LUFS) > 1.0:
        issues.append(f"loudness {m['input_i']} LUFS; target {LUFS}")
    if float(m["input_tp"]) > TRUE_PEAK + 0.5:
        issues.append(f"true peak {m['input_tp']} dBTP; limit {TRUE_PEAK}")
    if blacks:
        issues.append(f"black frames at {', '.join(blacks)}s")
    notes = list(notes)
    if dur > 90.5:
        notes.append(f"runs {dur:.1f}s: Facebook's Reels API takes at most 90 s")
    if ai_clips_as_stills:
        notes.append(f"{ai_clips_as_stills} ai_clip shot(s) rendered as still drift")
    return {
        "passed": not issues,
        "issues": issues,
        "notes": notes,
        "duration_s": round(dur, 2),
        "lufs": float(m["input_i"]),
        "true_peak_db": float(m["input_tp"]),
        "size_mb": round(int(info["format"]["size"]) / 1e6, 1),
    }


# ---------------------------------------------------------------- the whole render


def render(
    *,
    board: Storyboard,
    shots: list[TimedShot],
    frames: dict[str, Path],
    voice: VoiceTrack,
    caps: list[Caption],
    out_dir: Path,
    brand_dir: Path,
    music_dir: Path,
    seed: str,
    recent_music: Sequence[str] = (),
    thumb_src: Path | None = None,
    thumb_text: str = "",
    fps: int = 30,
    crf: int = 20,
) -> RenderResult:
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out_dir / "build"
    tmp.mkdir(exist_ok=True)

    # sound
    tracks = music.library(music_dir)
    cues = music.choose(music.sections(board, shots), tracks, recent_music, seed)
    mix = mix_audio(voice, board, shots, brand_dir, cues)
    raw_mix = ffmpeg.write_wav(tmp / "mix.wav", mix / max(1.0, float(np.max(np.abs(mix)))))
    final_mix = tmp / "mix_norm.wav"
    normalise(raw_mix, final_mix)

    # picture
    inputs: list[str] = []
    for shot in shots:
        prepared = prepare_frame(frames[shot.id], tmp / f"{shot.id}.jpg")
        inputs += ["-i", str(prepared)]
    ass = tmp / "captions.ass"
    ass.write_text(captions_ass(caps), encoding="utf-8")
    cameras = {s.id: s.camera for s in board.shots}
    extra: list[str] = []
    light = None
    if board.fade_out == "sunray":
        rays = sun_rays(tmp / "sun_rays.png")
        extra = ["-loop", "1", "-framerate", str(fps), "-t", f"{voice.duration_s:.3f}",
                 "-i", str(rays)]  # fmt: skip
        light = f"{len(shots) + 1}:v"
    graph = picture_filter(shots, cameras, fps, ass, board.fade_out, voice.duration_s, light)
    (tmp / "graph.txt").write_text(graph, encoding="utf-8")  # kept for debugging a render
    master = out_dir / "episode.mp4"
    ffmpeg.run(
        ["-loglevel", "error", *inputs, "-i", str(final_mix), *extra,
         "-filter_complex", graph, "-map", "[out]", "-map", f"{len(shots)}:a",
         "-c:v", "libx264", "-preset", "medium", "-crf", str(crf), "-r", str(fps),
         "-maxrate", "4500k", "-bufsize", "9M", "-pix_fmt", "yuv420p",
         # Meta's Reels spec: a closed GOP of 2-5 s and stereo AAC at 48 kHz
         "-g", str(fps * 2), "-keyint_min", str(fps * 2), "-sc_threshold", "0",
         "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-t", f"{voice.duration_s:.3f}",
         "-movflags", "+faststart", str(master)]
    )  # fmt: skip
    preview = out_dir / "preview.mp4"
    ffmpeg.run(
        ["-loglevel", "error", "-i", str(master), "-vf", "scale=720:1280", "-c:v", "libx264",
         "-preset", "veryfast", "-crf", "27", "-c:a", "aac", "-b:a", "128k",
         "-movflags", "+faststart", str(preview)]
    )  # fmt: skip

    cover = None
    if thumb_src is not None:
        cover = thumbnail(thumb_src, thumb_text, out_dir / "thumbnail.jpg")

    by_id = {s.id: s for s in board.shots}
    clips = sum(by_id[s.id].motion == "ai_clip" for s in shots)
    report = qc(master, voice.duration_s, music_notes(cues, not tracks), clips)
    report["music"] = [c.to_json() for c in cues if c.track is not None]
    report["music_credits"] = music.credits(cues)
    return RenderResult(master, preview, cover, report["duration_s"], report)
