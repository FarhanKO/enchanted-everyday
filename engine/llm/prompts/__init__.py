"""Agent role prompts, versioned together.

Each role's system prompt is its role file (this folder) followed by the brand documents it needs,
read from BRAND_DIR. Numbers in role files (`${max_hook_words}`, ...) come from the contracts in
engine/llm/schemas.py, so a prompt can't drift from what validation enforces.

Bump PROMPT_VERSION whenever a role file changes. Every script row records the version it was
written with, and `engine eval` compares versions on the golden set.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from string import Template
from typing import get_args

from engine.llm import schemas as s

PROMPT_VERSION = "v5"  # v5: assigned leads (Tina/Fann mix), D10 where they meet

HERE = Path(__file__).parent

# role -> brand files appended after the role prompt, in order
ROLES: dict[str, tuple[str, ...]] = {
    "story_architect": ("story_bible.md", "dreams_thread.md", "cast.toml"),
    "script_writer": ("story_bible.md", "dreams_thread.md", "production_style.md", "voices.toml"),
    "visual_director": ("story_bible.md", "production_style.md", "cast.toml", "sound.toml"),
    "packager": ("story_bible.md", "production_style.md"),
    "critic": ("story_bible.md", "dreams_thread.md", "cast.toml"),  # reviews card + script only
}

NUMBERS = {
    "max_hook_words": s.MAX_HOOK_WORDS,
    "min_words": s.MIN_WORDS,
    "max_words": s.MAX_WORDS,
    "pace_wpm": s.PACE_WPM,
    "min_s": s.MIN_DURATION_S,
    "max_s": s.MAX_DURATION_S,
    "min_shots": s.MIN_SHOTS,
    "max_shots": s.MAX_SHOTS,
    "max_ai_clips": s.MAX_AI_CLIPS,
    "tolerance_s": s.DURATION_TOLERANCE_S,
    "max_speakers": s.MAX_SPEAKERS,
    "min_mixed_lines": s.MIN_MIXED_CHARACTER_LINES,
    "speakers": ", ".join(f"`{x}`" for x in get_args(s.Speaker)),
}


def role_prompt(role: str) -> str:
    text = (HERE / f"{role}.md").read_text(encoding="utf-8")
    return Template(text).substitute(NUMBERS)  # a missing number fails loudly


@lru_cache
def system_prompt(role: str, brand_dir: Path) -> str:
    parts = [role_prompt(role)]
    for name in ROLES[role]:
        tag = Path(name).stem
        body = (brand_dir / name).read_text(encoding="utf-8").strip()
        parts.append(f"<{tag}>\n{body}\n</{tag}>")
    return "\n\n".join(parts)
