# content-engine

A code-first pipeline that publishes one approved 30-60 second vertical video a day to YouTube,
Instagram, TikTok and Facebook. The LLM writes text inside fixed stages. It never takes actions,
and nothing posts without a human tap.

```
trend scan -> pick idea -> script + critic -> assets -> render + QC -> approve (Telegram) -> publish -> analytics
```

**Status:** Phase 0 (setup). Built so far: the repo, Compose stack, schema, CI, the stage runner and the trend scan.
See [the roadmap](#roadmap).

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
  and then re-validated: 110-150 words, a real source URL on every claim, and sources limited to pages we fetched
  ([engine/llm/](engine/llm/)).
- **A hard daily spend cap.** Every LLM call is costed and committed before the next one is allowed ([engine/budget.py](engine/budget.py)).

## Quick start (local)

Requires Docker.

```bash
cp .env.example .env        # fill in what you have; DRY_RUN=true by default
docker compose up -d --build
docker compose run --rm worker engine check
docker compose run --rm worker engine run   # one daily run now
```

Without Docker (unit tests only):

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest            # DB tests run when TEST_DATABASE_URL points at Postgres+pgvector
```

## Layout

```
engine/
  config.py          settings from env (.env.example lists them all)
  flows.py           Prefect daily flow
  db/                models + Alembic migrations (10 tables)
  llm/               Claude client, JSON-schema contracts, pricing
  stages/            trend (built); idea, script, assets, render, approve, publish, analytics (next)
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
