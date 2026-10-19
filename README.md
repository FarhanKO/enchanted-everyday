# content-engine

The studio behind **The Enchanted Everyday** (modern fairy tales for sleepless souls): cinematic 45-90 second micro-fables about ordinary
people, strange places and very big feelings, published to YouTube Shorts, Instagram Reels, TikTok and Facebook.
The LLM writes inside fixed stages and never takes actions. Nothing posts without a human tap.

```
daily:      discovery -> story card -> script -> critic -> script to Telegram
/redo:      next backup story -> script -> critic -> script to Telegram   (with your note, if any)
/produce:   storyboard -> package -> package to Telegram
            -> voice + frames -> render + QC -> video to Telegram -> Approve / Skip
/reshoot:   one frame redrawn (with your note, if any) -> render + QC -> video to Telegram
Approve:    Instagram + Facebook Reels posted (YouTube after its audit) -> links to Telegram
            -> posting kit for the platforms still posted by hand (TikTok)
next:       analytics (Phase 4)
```

**Status:** Phases 0-3 are built. Each daily run picks a premise, writes the script, has the critic review it
and sends it to Telegram. Send `/redo` (optionally `/redo less sad`) to turn the story down and get the next backup
written instead; a script you'd reject never costs a storyboard. Send `/produce` and the bot writes the storyboard
and package, voices every line in the cast's voices, draws each frame with the cast's reference images, renders
the 9:16 video with captions, sound and the signature ending, and sends it with **Approve / Skip** buttons.
`/reshoot S03 warmer light` redraws one frame. Approve posts the Reel to Instagram and Facebook with Meta's AI
label (and to YouTube once `YOUTUBE_UPLOAD_ENABLED=true`), replies with the links, and sends the posting kit for
TikTok. `/publish` retries a platform that failed. Nothing posts while `DRY_RUN=true`. See
[the roadmap](#roadmap) and [docs/decisions.md](docs/decisions.md).

## Architecture

Everything except the platforms and outside APIs runs in one Docker Compose stack on a single VPS:

| Service | Role |
|---|---|
| `postgres` | pgvector/Postgres 16: all state, metrics, idea embeddings |
| `prefect-server` | schedules, retries, run history (UI on `localhost:4200` via SSH tunnel) |
| `migrate` | one-shot Alembic upgrade before anything else starts |
| `worker` | the daily flow (`engine serve`) |
| `bot` | Telegram bot, long polling, owner-only |

Design rules:

- **Every stage is keyed on (run date, stage name).** A stage's writes and its "done" marker commit together,
  so a retry resumes where the day failed instead of starting over ([engine/stages/base.py](engine/stages/base.py)).
- **Publishing is idempotent.** The `posts` table is checked, and locked, before any upload. An upload
  interrupted mid-way is flagged for a human rather than retried blind ([engine/publishers/base.py](engine/publishers/base.py)).
- **The LLM gets text in and gives JSON out.** It gets no tools and no shell. Output is constrained by a JSON schema
  and then re-validated: the six-beat formula, 45-84 s of script at narration pace (within 90 s with the ending),
  characters heard in their own voices rather than quoted, a contiguous storyboard with a music mood per shot, known characters
  only, at most 2 AI clips, and no named artists or studios ([engine/llm/schemas.py](engine/llm/schemas.py)).
- **Locked prompt fragments.** Agents write only the shot-specific text. Code appends character descriptors, locations
  and the style block verbatim, so every frame shares identical identity and style text ([engine/prompting.py](engine/prompting.py)).
- **Contracts are repaired, not trusted.** An answer that breaks its contract goes back to the agent with the
  errors, up to 3 tries. The critic's notes drive one script revision; a rejected story falls back to a backup
  idea ([engine/studio.py](engine/studio.py)). Each agent can run on its own model and effort (`LLM_MODELS`,
  `LLM_EFFORTS`); by default all use Opus 5.5, with the script writer and critic at high effort.
- **A hard daily spend cap.** Every LLM call is costed and committed before the next one is allowed ([engine/budget.py](engine/budget.py)).

## Quick start (local)

Requires Docker.

```bash
cp .env.example .env        # fill in what you have; DRY_RUN=true by default
docker compose up -d --build
docker compose run --rm worker engine check
docker compose run --rm worker engine run       # one daily run now
docker compose run --rm worker engine produce   # storyboard, package and video for today's script
docker compose run --rm worker engine redo --note "less sad"   # turn today's story down
```

Validate an episode and render its review document:

```bash
python -m engine episode stories/s000-the-man-who-sold-his-dreams/episode.json
```

Render an episode.json to video without the database (voice and frames are paid for, at most `--max-usd`;
`--only S01` draws one frame to check the look first). Everything bought is cached under `WORK_DIR`, so a re-run
is free:

```bash
python -m engine render stories/s000-the-man-who-sold-his-dreams/episode.json --max-usd 1
```

Check a prompt change against the golden set (every approved `stories/*/episode.json`). This calls the real
model, so it costs money:

```bash
python -m engine eval --max-usd 3
```

Without Docker (unit tests only):

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest            # DB tests run when TEST_DATABASE_URL points at Postgres+pgvector
```

## Layout

```
brand/               story bible, production style, locked prompt fragments, 20-story slate
stories/             hand-built and approved episodes (episode.json + rendered episode.md)
schemas/             JSON Schema export of the agent contracts (`engine schemas`)
engine/
  config.py          settings from env (.env.example lists them all)
  flows.py           Prefect daily flow
  db/                models + Alembic migrations (11 tables)
  llm/               Claude client, episode contracts, pricing, role prompts (llm/prompts/)
  studio.py          the story agents, contract repair and critic-driven script revision
  embeddings.py      local MiniLM embeddings for the duplicate-story check
  evals.py           golden-set eval (`engine eval`)
  prompting.py       final image/video prompt assembly
  episode_doc.py     Episode JSON -> review document
  stages/            daily: discovery, idea, script + critic (story.py), deliver_script;
                     production: storyboard + package (story.py), deliver_package; then
                     voice, images, render, deliver_render (media.py)
  media/             voice track, frames, sounds made in code, timing + captions, ffmpeg render + QC;
                     paid calls cached so nothing is bought twice (paid.py)
  approval.py        Approve / Skip, the posting kit, /reshoot
  publish.py         Approve -> every platform that posts automatically; /publish, /posted
  publishers/        idempotent publish guard; meta.py (Instagram, Facebook Reels), youtube.py
  storage.py         Cloudflare R2 (backups; publishing uploads the file directly)
  budget.py          daily spend cap (LLM calls and paid media)
  redo.py            /redo: swap the day's story for the next backup
  tokens.py          daily Meta and YouTube login check, fix-it steps to Telegram
  notify.py          Telegram alerts, videos + dead-man's-switch ping
bot/                 Telegram bot (/status, /produce, /redo, /reshoot, /publish, /posted, Approve / Skip)
evals/               eval results per prompt version
templates/           caption font (Lora) and the licensed music library
docs/                ADRs, runbook, platform setup, privacy policy
scripts/             VPS provisioning and deploy
```

## Roadmap

| Phase | Dates (2026) | Exit check |
|---|---|---|
| 0 Setup and API access | Oct 5-11 | CI deploys to the VPS; every platform application submitted |
| 1 Trends, ideas, scripts | Oct 12-18 | You'd approve at least 5 of 7 daily scripts |
| 2 Video and approval bot | Oct 19-25 | First approved video posted by hand on all four |
| 3 Auto-publishing | Oct 26-Nov 1 | **MVP gate:** IG and FB post automatically after the tap |
| 4 Analytics loop | Nov 2-8 | A full week of metrics for every post |
| 5 Hardening | Nov 9-15 | Seven days without a manual fix |
| 6 Learning and portfolio | Nov 16-29 | **Production gate:** 14 days at 95% or better on time |

Open decisions: [docs/decisions.md](docs/decisions.md). Platform approvals: [docs/platform-setup.md](docs/platform-setup.md).
