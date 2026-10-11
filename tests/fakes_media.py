"""Stand-ins for the paid image and speech APIs: deterministic, free, offline."""

from __future__ import annotations

import hashlib
import io
import wave
from decimal import Decimal

import numpy as np
from PIL import Image as PILImage
from PIL import ImageDraw

from engine.media.openrouter import Image

RATE = 48_000


def fake_speech(text: str, model: str, voice: str) -> bytes:
    """A murmur as long as the line would take at ~2.6 words a second, with a little lead-in
    silence like real TTS. WAV bytes (ffmpeg decodes by content, whatever the file is called)."""
    words = max(1, len(text.split()))
    seconds = words / 2.6
    t = np.arange(int(seconds * RATE)) / RATE
    pitch = 110 + sum(map(ord, voice)) % 80
    tone = 0.3 * np.sin(2 * np.pi * pitch * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 3 * t))
    audio = np.concatenate([np.zeros(int(0.15 * RATE)), tone, np.zeros(int(0.2 * RATE))])
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((audio * 32767).astype("<i2").tobytes())
    return buf.getvalue()


def fake_image(prompt: str, model: str, refs: list) -> Image:
    """A labelled gradient at the model's 9:16 1K size."""
    img = PILImage.new("RGB", (768, 1376))
    draw = ImageDraw.Draw(img)
    seed = int(hashlib.sha256(prompt.encode()).hexdigest(), 16) % 255
    for y in range(img.height):
        shade = int(40 + 120 * y / img.height)
        draw.line([(0, y), (img.width, y)], fill=(seed // 3, shade // 2, shade))
    draw.ellipse([284, 600, 484, 800], fill=(240, 190, 90))
    draw.text((40, 40), prompt[:60], fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return Image(data=buf.getvalue(), mime="image/png", model=model, cost_usd=Decimal("0.04"))
