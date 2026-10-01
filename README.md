# content-engine

The studio behind **Modern Fairy Tales for Sleepless Souls**: cinematic 45-90 second micro-fables about ordinary
people, strange places and very big feelings, published to YouTube Shorts, Instagram Reels, TikTok and Facebook.
The LLM writes inside fixed stages and never takes actions. Nothing posts without a human tap.

```
discovery -> story card -> script -> storyboard -> package -> critic
          -> images + voice + sound -> render + QC -> approve (Telegram) -> publish -> analytics
```

**Status:** Phase 0 is complete, and Phase 1 has started. The brand kit ([brand/](brand/)), episode contracts
([engine/llm/schemas.py](engine/llm/schemas.py)) and the first hand-built episode
([stories/s000-the-man-who-sold-his-dreams](stories/s000-the-man-who-sold-his-dreams/episode.md)) are done.
See [the roadmap](#roadmap) and [docs/decisions.md](docs/decisions.md).

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
  and then re-validated: the six-beat formula, 45-90 s at narration pace, a contiguous storyboard, known characters
  only, at most 2 AI clips, and no named artists or studios ([engine/llm/schemas.py](engine/llm/schemas.py)).
- **Locked prompt fragments.** Agents write only the shot-specific text. Code appends character descriptors, locations
  and the style block verbatim, so every frame shares identical identity and style text ([engine/prompting.py](engine/prompting.py)).
- **A hard daily spend cap.** Every LLM call is costed and committed before the next one is allowed ([engine/budget.py](engine/budget.py)).

## Quick start (local)

Requires Docker.

```bash
cp .env.example .env        # fill in what you have; DRY_RUN=true by default
docker compose up -d --build
docker compose run --rm worker engine check
docker compose run --rm worker engine run   # one daily run now
```

Validate an episode and render its review document:

```bash
python -m engine episode stories/s000-the-man-who-sold-his-dreams/episode.json
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
  llm/               Claude client, episode contracts, pricing
  prompting.py       final image/video prompt assembly
  episode_doc.py     Episode JSON -> review document
  stages/            discovery (built); idea, script, storyboard, package, assets, render, approve, publish
  publishers/        idempotent publish guard; one module per platform in Phase 3
  storage.py         Cloudflare R2
  budget.py          daily spend cap
  notify.py          Telegram alerts + dead-man's-switch ping
bot/                 Telegram bot
evals/               golden scripts + rubric (Phase 1)
templates/           fonts, caption styles, stings (Phase 2)
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
