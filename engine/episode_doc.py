"""Render an Episode as a human-readable production package (Markdown).

Agents produce JSON; people review this. The same text feeds the Telegram approval message.
"""

from __future__ import annotations

from engine import prompting
from engine.llm.schemas import PACE_WPM, Episode


def _t(seconds: float) -> str:
    return f"{int(seconds // 60)}:{seconds % 60:04.1f}"


def to_markdown(ep: Episode) -> str:
    card, script, board, pkg = ep.card, ep.script, ep.storyboard, ep.package
    chars = {c.id: c for c in board.characters}
    out: list[str] = []
    w = out.append

    w(f"# {pkg.title}\n")
    w(
        f"`{ep.id}` · universe **{card.universe}** · "
        f"{script.word_count} words · ~{script.estimated_duration_s:.0f}s narration · "
        f"{board.duration_s:.0f}s cut\n"
    )
    w(f"> {card.premise}\n")
    w(f"- **Feeling:** {card.human_emotion}")
    w(f"- **Magic:** {card.magical_element}")
    w(f"- **Visual anchor:** {card.visual_anchor}")
    w(f"- **Ending image:** {card.ending_image}")
    w(f"- **Leaves them thinking:** {card.lingering_question}")
    w(f"- **Universe:** {', '.join(card.recurring) or 'none'}\n")

    w("## 1. Script\n")
    w(f"_{script.narration_direction}_\n")
    for beat in script.beats:
        w(f"**{beat.name.upper()}**\n")
        for line in beat.lines:
            pause = f" _[pause {line.pause_after_s:g}s]_" if line.pause_after_s >= 0.5 else ""
            w(f"> {line.text}{pause}  ")
        w("")

    w("## 2. Storyboard\n")
    w("| Shot | Time | Beat | Camera | Motion | What we see |")
    w("|---|---|---|---|---|---|")
    for s in board.shots:
        w(
            f"| {s.id} | {_t(s.start_s)}-{_t(s.end_s)} | {s.beat} | {s.camera} | {s.motion} "
            f"| {s.description} |"
        )
    w("")

    w("## 3. Image prompts\n")
    w("Shot text from the storyboard, plus locked descriptors and style block appended by code.\n")
    for s in board.shots:
        p = prompting.image_prompt(s, board)
        w(f"**{s.id}** ({s.pole})\n\n```text\n{p.prompt}\n```\n")
    w(f"**Negative (all shots):** `{prompting.style()['style']['negative']}`\n")

    w("## 4. Video prompts\n")
    for s in board.shots:
        tag = "**AI clip**" if s.motion == "ai_clip" else "code drift (fallback prompt)"
        w(f"- **{s.id}** ({tag}): {prompting.video_prompt(s)}")
    w("")

    w("## 5. Characters and locations (consistency sheet)\n")
    for c in board.characters:
        flag = " · recurring" if c.recurring else ""
        w(f"- **{c.name}** (`{c.id}`, {c.role}{flag})  ")
        w(f"  {c.descriptor}  \n  _Anchor:_ {c.signature}")
    for loc in board.locations:
        w(f"- **{loc.name}** (`{loc.id}`, {loc.pole})  ")
        w(f"  {loc.descriptor}  \n  _Light:_ {loc.lighting}")
    w("")

    w("## 6. Narration\n")
    w(f"{script.narration_direction} Target pace {PACE_WPM} wpm.\n")
    w("| Line | Delivery | Pause |")
    w("|---|---|---|")
    for line in script.lines:
        w(f"| {line.text} | {line.delivery} | {line.pause_after_s:g}s |")
    w("")

    w("## 7. Music and sound\n")
    w(f"**Music:** {board.sound.music_palette}\n")
    for cue in board.sound.cues:
        w(f"- `{_t(cue.at_s)}` **{cue.action}**: {cue.note}")
    w(f"\n**Ambience:** {', '.join(board.sound.ambience)}\n")
    w("**SFX by shot:**\n")
    for s in board.shots:
        if s.sfx:
            w(f"- {s.id}: {', '.join(s.sfx)}")
    w("")

    w("## 8. Subtitles\n")
    w(
        "Brand standard (`brand/production_style.md` section 6): phrase-level chunks of 2-6 "
        "words, Lora SemiBold, warm cream with a soft shadow, at most one gold key word, "
        "baseline at 72% height, no captions during pauses.\n"
    )

    w("## 9. Title and thumbnail\n")
    w(f"- **Title:** {pkg.title}")
    w(f"- **A/B titles:** {' / '.join(pkg.alt_titles)}")
    w(f"- **Thumbnail:** {pkg.thumbnail.concept}")
    w(f"- **Thumbnail text:** {pkg.thumbnail.text or '(none)'}\n")
    thumb = prompting.thumbnail_prompt(pkg.thumbnail, board)
    w(f"```text\n{thumb.prompt}\n```\n")

    w("## 10. Publishing package\n")
    pc = pkg.platforms
    tags = " ".join(pc.hashtags)
    w(f"**YouTube Shorts:** {pc.youtube_title}\n")
    w(f"```text\n{pc.youtube_description}\n\n{tags}\n```\n")
    w(f"**TikTok:**\n\n```text\n{pc.tiktok_caption} {tags}\n```\n")
    w(f"**Instagram Reels:**\n\n```text\n{pc.instagram_caption}\n\n{tags}\n```\n")
    w(f"**Facebook Reels:**\n\n```text\n{pc.facebook_caption}\n```\n")
    w(f"- **Pinned comment:** {pkg.comment_prompt}")
    w(f"- **Long-form path:** {pkg.long_form_path}")
    w("- **AI disclosure:** on for every platform (AI-assisted artwork)\n")

    w("## 11. Schema\n")
    w("This package is an `Episode` (`engine/llm/schemas.py`). JSON Schema files: `schemas/`.\n")
    used = {cid for s in board.shots for cid in s.characters}
    if unused := set(chars) - used:
        w(f"_Note: characters defined but never shown: {', '.join(sorted(unused))}_\n")
    return "\n".join(out)
