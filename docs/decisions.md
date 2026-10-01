# Decisions

The architecture is settled (see `adr/`). This file tracks the content decisions.

| Decision | Choice | Decided | Notes |
|---|---|---|---|
| Niche | **Modern Fairy Tales for Sleepless Souls**: cinematic micro-fables, 70% dark urban / 30% cozy bedtime | 2026-10-01 | Brief: `brand/story_bible.md`, `brand/production_style.md` |
| Language | **English** | 2026-10-01 | |
| Story structure | **Three universes**: Urban Fairy Tales 40%, Emotional Fairy Tales 30%, Bedtime Fables 30% | 2026-10-01 | Replaces the brief's 5 pillars / 2 lanes; keeps its 70/30 split. Shares live in `engine/stages/discovery.py` |
| Core creative rules | **Your seven rules** (+5 craft rules from the brief) | 2026-10-01 | Rules 4 and 6 enforced in code |
| Voice | _open_ | by Oct 4 | Your recorded voice (default) or TTS. See below |
| Visual style | **AI-illustrated painterly frames** (night and day poles), code-animated drift, at most 2 AI video clips per episode | 2026-10-01 | Follows from the niche |
| Image model | _open_ | by Oct 18 | Must support reference-image conditioning for character consistency |
| Cadence | _open_ | by Oct 18 | Plan says daily; the brief says 3-5 a week until quality is stable. See below |
| Audience timezone | _open_ | by Oct 25 | Sets the publish slot ("late-night viewers"), e.g. US evening |
| TikTok route | _open_ | by Oct 25 | Default: manual until inbox upload is approved |

## What the niche changed in the build plan

The original plan assumed a factual, news-driven niche. Fiction changes these parts:

| Plan item | Was | Now |
|---|---|---|
| Stage 1 | Trend scan (Google Trends, RSS, YouTube) | **Discovery**: the story slate (`brand/slate.toml`), balanced across the three universes; audience comments join in Phase 4 |
| Stage 3 | Script + fact-checking critic, a source URL on every claim | **Story chain**: story card -> script (6-beat formula) -> storyboard -> package, with a critic that checks the seven core rules and five craft rules |
| Length | 110-150 words, 30-60 s | 80-190 words at 120 wpm, **45-90 s** with scripted pauses |
| Visuals | Pexels stock footage + code-drawn charts | **AI-generated painterly frames**, 6-14 per episode, plus a thumbnail |
| Motion | Stock clips | Slow drift/parallax in code by default; at most 2 AI video clips |
| Captions | Word-by-word | **Phrase-level**, calm (the brand forbids frantic captions) |
| AI disclosure | Only when realistic AI is used | **Every post**: the artwork is AI-assisted |
| Data | 10 tables | 11: adds `bible_entries` for recurring characters and places with locked descriptors and reference images |

## Open: voice

The brief wants "a secret told at 2 AM". Options:

1. **Your recorded voice** (plan default). The strongest originality signal for YouTube monetization and the most human.
   About 3 minutes a day to record 150 words plus retakes. Accent is fine; calm delivery matters more.
2. **A clone of your own voice.** Consistent, no daily recording, still your voice. Disclose that it's synthetic.
3. **Stock TTS.** Fastest, but the most "generic AI channel"-like, and that is exactly what YouTube's inauthentic-content
   policy targets.

## Open: cadence and budget

AI art makes the per-episode cost higher than stock footage. A rough estimate, to confirm once the image model is chosen:
about 14 images with retries, plus 2 short AI clips, comes to roughly **$1-3 per episode**.

- Daily: about $30-90 a month on top of the ~$11-25 baseline. That breaks the plan's "< $30/month" target
- 3-5 a week: about $12-60 a month

The brief also says "daily posting only after quality and workflow are stable." **Recommendation:** run 3-5 a week from
Nov 1, and switch to daily after the production gate (Nov 29) if cost per episode and approval rate allow it. The
on-time KPI then measures scheduled slots, not calendar days.

## Policy notes for this niche

- **YouTube inauthentic content:** narrated AI-image slideshows are the format most at risk of demonetization.
  The mitigations are your voice, original stories, directed motion and sound, varied structure, and the
  recurring universe.
- **No named styles:** prompts never name studios or artists. Validation rejects them (`BANNED_STYLE_TERMS`).
  The references are described by attributes instead.
- **Children:** some stories feature children (Bedtime Fables). Keep them safe and dignified. No peril as a hook.
