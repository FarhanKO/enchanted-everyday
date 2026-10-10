"""Audition the voice cast: one mp3 per role in brand/voices.toml, through OpenRouter.

    python scripts/voice_samples.py [out_dir]          (default: voice_samples/)

Costs about a cent for the whole cast. Needs OPENROUTER_API_KEY in .env and the ElevenLabs
provider allowed at openrouter.ai/settings/privacy. Children are pitch-lifted with ffmpeg
(rubberband), as the pipeline will do.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.config import get_settings  # noqa: E402

SPEECH_URL = "https://openrouter.ai/api/v1/audio/speech"


def speak(key: str, model: str, voice: str, text: str) -> bytes:
    resp = httpx.post(
        SPEECH_URL,
        headers={"Authorization": f"Bearer {key}"},
        json={"model": model, "input": text, "voice": voice, "response_format": "mp3"},
        timeout=120,
    )
    if resp.status_code != 200:
        raise SystemExit(f"{voice}: HTTP {resp.status_code} {resp.text[:300]}")
    return resp.content


def pitch(src: Path, semitones: float) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise SystemExit("ffmpeg is not on PATH; needed to pitch-lift the children's voices")
    ratio = 2 ** (semitones / 12)
    out = src.with_name(src.stem + "_raw.mp3")
    src.rename(out)
    subprocess.run(  # noqa: S603 - fixed arguments; the paths are files this script just wrote
        [ffmpeg, "-y", "-loglevel", "error", "-i", str(out),
         "-af", f"rubberband=pitch={ratio:.4f}:formant=shifted", str(src)],
        check=True,
    )  # fmt: skip
    out.unlink()


def main() -> None:
    settings = get_settings()
    if not settings.openrouter_api_key:
        raise SystemExit("OPENROUTER_API_KEY is not set")
    key = settings.openrouter_api_key.get_secret_value()
    cast = tomllib.loads((ROOT / settings.brand_dir / "voices.toml").read_text(encoding="utf-8"))
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "voice_samples")
    out_dir.mkdir(exist_ok=True)

    model = cast["model"]
    for role, spec in cast.items():
        if not isinstance(spec, dict):
            continue
        for voice in dict.fromkeys(filter(None, [spec["voice"], spec.get("backup")])):
            path = out_dir / f"{role}_{voice}.mp3"
            path.write_bytes(speak(key, model, voice, spec["sample"]))
            if semis := spec.get("pitch_semitones"):
                pitch(path, semis)
            print(f"ok  {path.name}")


if __name__ == "__main__":
    main()
