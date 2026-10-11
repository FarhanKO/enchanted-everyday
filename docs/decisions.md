# Decisions

The architecture is settled (see `adr/`). This file tracks the content decisions.

| Decision | Choice | Decided | Notes |
|---|---|---|---|
| Niche | **Modern Fairy Tales for Sleepless Souls**: cinematic micro-fables, 70% dark urban / 30% cozy bedtime | 2026-10-01 | Brief: `brand/story_bible.md`, `brand/production_style.md` |
| Channel name | **The Enchanted Everyday** (YouTube @TheEnchantedEveryday); "Modern fairy tales for sleepless souls" is the tagline | 2026-10-10 | Setup kit: `docs/youtube-channel.md` |
| Language | **English** | 2026-10-01 | |
| Story structure | **Three universes**: Urban Fairy Tales 40%, Emotional Fairy Tales 30%, Bedtime Fables 30% | 2026-10-01 | Replaces the brief's 5 pillars / 2 lanes; keeps its 70/30 split. Shares live in `engine/stages/discovery.py` |
| Core creative rules | **Your seven rules** (+5 craft rules from the brief) | 2026-10-01 | Rules 4 and 6 enforced in code |
| Voice | **ElevenLabs Eleven v4 built-in voices through OpenRouter** (same key, ~$0.04 an episode, no subscription). Cast in `brand/voices.toml`: narrator George, Fann Brian, Tina Jessica, Shopkeeper Lily, children Laura/Liam pitch-lifted | 2026-10-10 | Built-in voices can't be cloned or tuned through OpenRouter; your own clone stays possible later with a direct ElevenLabs key. ElevenLabs retires its default voices after 2026-12-31, so expect to re-pick then. Disclose the synthetic voice on every post |
| Visual style | **AI-illustrated painterly frames** (night and day poles), code-animated drift, at most 2 AI video clips per episode | 2026-10-01 | Follows from the niche |
| Image model | **Nano Banana 2.1** (`google/gemini-nano-banana-2.1`) via OpenRouter; Nano Banana 2 as fallback | 2026-10-10 | Successor to Nano Banana 2 and Pro, with reference-image editing for locked characters, at half NB2's image price (~$0.04 a frame vs ~$0.08). Released 2026-10-06, so A/B it against NB2 on the cast sheet before locking |
| Video model | **Kling 3.0 Pro** (Kling Open Platform API) for the at most 2 AI clips per episode | 2026-10-10 | "Kimi" is Moonshot's text model; Kling is the video one. Resellers quote $0.06-0.58 per second, so confirm the official price; ~10 s a day dominates the per-episode cost |
| LLM route | **Opus 5.5 for every agent, through OpenRouter** (`OPENROUTER_API_KEY`) | 2026-10-10 | Same Anthropic Messages request and JSON-schema contracts via OpenRouter's Anthropic-compatible API; same price. Keys live only in `.env`, never in the database |
| Five pillars | Visual identity, narrator's personality, signature ending, characters' sounds, connected stories | 2026-10-10 | In `brand/story_bible.md` ("The five pillars"); every agent reads it |
| Story types and modes | **Fable** (most) or **daily** (~1 in 4); **narrated ~40% / mixed ~40% / dialogue ~20%**, picked by what the story is; at most 3 speaking characters; every line names its speaker | 2026-10-10 | Speakers checked against the mode in code (`check_speakers`); the architect sees the recent mix |
| Signature ending | Final frame holds ~3 s, the Shopkeeper's moon bell, then the narrator: "Goodnight, sleepless soul." Every episode, every mode | 2026-10-10 | Added by code, never written by agents (`brand/sound.toml`) |
| Character sounds | Fann hums three falling notes (felt piano motif); Tina's dupatta rustle with a four-note music-box answer; the Shopkeeper's moon bell | 2026-10-10 | `brand/sound.toml`; the storyboard places each at the character's first appearance |
| Connected episodes | Every episode stands alone and names its connection. Fann and Tina are **strangers who keep crossing**. The long thread is **Fann's lost dreams**; the girl dreaming them in s000 is Tina (never told to viewers), ~1 episode in 5 | 2026-10-10 | Each produced episode leaves a canon note (`Package.canon`); story agents read the last 8 (`engine/canon.py`) |
| Cadence | **4 a week**: Sun, Tue, Thu, Sat at 05:00 (`DAILY_RUN_CRON=0 5 * * 0,2,4,6`) | 2026-10-10 | The brief's 3-5 a week until quality is stable; daily after the Nov 29 production gate if cost and approval rate allow |
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
| AI disclosure | Only when realistic AI is used | **Every post**, through each platform's AI label and the channel About text; no disclosure line in any description or caption (2026-10-11) |
| Data | 10 tables | 11: adds `bible_entries` for recurring characters and places with locked descriptors and reference images |

## Phase 1 build choices (2026-10-09)

These are engineering defaults. Change any of them if you disagree.

| Choice | Default | Why |
|---|---|---|
| Duplicate-story check | Cosine similarity of title + premise **>= 0.75** against every story already picked or published | Distinct slate stories top out at 0.63; close retellings of one story score about 0.8. Retune in week 2 (`engine/stages/idea.py`) |
| Embeddings | all-MiniLM-L6-v2 via **fastembed** (ONNX), not sentence-transformers | Same model and vectors without torch: the image stays about 1 GB smaller. Downloads ~90 MB on first use |
| If the duplicate check breaks | The day continues without it and you get a Telegram alert | Slate ids already stop exact repeats; one broken download shouldn't cost a day |
| Critic | Reviews the story card and script only, before any visuals. One revision round; a `reject` writes the first backup idea instead | Bounds cost. The critic advises and you decide: every script reaches you with its report |
| Turning a story down | `/redo [note]` swaps the day's story for the best remaining backup and writes, reviews and sends it again. Your note goes to the writer and critic, and the day's notes add up. Allowed until production starts; at most 2 a day (the backups) | Reuses the cards the story architect already scored, so a redo costs a script and a review (~$0.30), not a new batch. A turned-down slate story is never offered again (`engine/redo.py`) |
| Contract repair | Up to 3 tries per agent, each seeing its last answer and the validation errors | Fixes most near-misses (an over-long hook, a storyboard 12 s short) for one extra call |
| Script first | The daily run stops at the reviewed script. The storyboard and package are written only when you send `/produce` | A script you'd reject never costs a storyboard (~$0.25). Phase 2 swaps `/produce` for your voice note |
| Models | Opus 5.5 for every agent; the script writer and critic at `high` effort, the rest at `medium`. Override per agent with `LLM_MODELS` / `LLM_EFFORTS` | At this volume a second model saves $1-3 a month; effort is the better lever |

**Spend (estimates until the first real runs):** the daily run is 3 calls, about $0.30 with high effort on the script
and critic. `/produce` adds 2 calls, about $0.25. A revision adds about $0.15; a rejected story about $0.20; a `/redo` about $0.30. A
produced episode lands around $0.55-0.75. Phase 2's paid images share the $2.00 `DAILY_SPEND_CAP_USD`, so expect to
raise it then.

**Phase 2 spend (estimates):** about 10 frames at ~$0.04 (Nano Banana 2.1), up to 10 s of Kling 3.0 Pro at roughly
$0.11-0.24/s, and the ElevenLabs subscription. With the LLM that is about $2.00-3.50 per episode, so raise
`DAILY_SPEND_CAP_USD` to about $4 when Phase 2 lands, or make the AI clips optional.

## Voice (decided 2026-10-10: option 3, ElevenLabs built-in voices via OpenRouter)

The brief wants "a secret told at 2 AM". Options:

1. **Your recorded voice** (plan default). The strongest originality signal for YouTube monetization and the most human.
   About 3 minutes a day to record 150 words plus retakes. Accent is fine; calm delivery matters more.
2. **A clone of your own voice.** Consistent, no daily recording, still your voice. Disclose that it's synthetic.
3. **Stock TTS.** Fastest, but the most "generic AI channel"-like, and that is exactly what YouTube's inauthentic-content
   policy targets.

## Cadence and budget (decided 2026-10-10: 4 a week)

AI art makes the per-episode cost higher than stock footage. A rough estimate, to confirm once the image model is chosen:
about 14 images with retries, plus 2 short AI clips, comes to roughly **$1-3 per episode**.

Update 2026-10-10: Farhan can't spend ~$2 a day. Writing stays all Opus 5.5 (~$0.55 per episode). The levers left for
Phase 2: no Kling clips by default (code-animated drift is the house style), ~8 Nano Banana 2.1 frames at 1K upscaled
locally with reused location plates (~$0.20-0.27), and a cheap voice route. At 4 a week that is roughly $15-20 a month
plus the voice.

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
