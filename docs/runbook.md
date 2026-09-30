# Runbook

All times are Dhaka (Asia/Dhaka).

## A normal day

| Time | What runs | You do |
|---|---|---|
| 05:00 | Trend scan, idea pick, script, critic pass | Nothing |
| 07:30 | Bot sends the day's script | Reply with a voice note (~3 min; skipped with TTS) |
| On reply | Assets, render, QC checks | Nothing |
| After render | Preview, captions and sources arrive | Approve, Redo or Skip (~5 min) |
| 12:00 | Approval cutoff. An unapproved day publishes from the buffer or is skipped | Nothing |
| Audience evening | Staggered publish to all four; TikTok draft lands in your inbox | Tap Post in TikTok until automated |
| +24 h, +7 d | Stats pulled for every post | Nothing |
| Sunday 10:00 | Weekly report in Telegram | 30-minute review; adjust prompts or formats |

Keep three approved videos in the buffer so exams or travel never break the streak.

## Commands (on the VPS, in /opt/content-engine)

```bash
docker compose ps                                   # what's running
docker compose logs -f worker                       # JSON logs
docker compose run --rm worker engine check         # settings + DB check
docker compose run --rm worker engine run           # run today now
docker compose run --rm worker engine run --date 2026-10-12   # re-run a day (finished stages are skipped)
ssh -L 4200:localhost:4200 app@<vps>                # then open http://localhost:4200 for the Prefect UI
```

## When something breaks

**Daily run failed (Telegram alert).** Read the stage and error in the alert, then `docker compose logs worker`.
Fix the cause and re-run the day with `engine run --date <day>`. Finished stages don't run again.

**Dead-man's switch fired (no check-in by 09:00).** The worker isn't running or is stuck.
Run `docker compose ps` and restart with `docker compose up -d`. Then re-run the day.

**`PublishStateUnknown`.** An upload was interrupted and the post may or may not be live. Check the platform.
- If it's live: `UPDATE posts SET status='published', external_id='<id>', url='<url>' WHERE id=<n>;`
- If not: `UPDATE posts SET status='failed' WHERE id=<n>;` and re-run.

Open a SQL shell with `docker compose exec postgres psql -U engine`.

**`BudgetExceeded`.** The daily cap stopped a run. Check `runs.llm_cost_usd` and the logs for a retry loop
before raising `DAILY_SPEND_CAP_USD`.

**`invalid_grant` / auth errors.** A platform token expired or was revoked. Re-authorize and update `.env`,
then `docker compose up -d` to reload.

## Backups (Phase 5)

Nightly `pg_dump` to R2, kept 14 days. Test a restore once a month.
