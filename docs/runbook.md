# Runbook

All times are Dhaka (Asia/Dhaka).

## A normal day

| Time | What runs | You do |
|---|---|---|
| 05:00 | Story pick, script, critic pass | Nothing |
| ~05:05 | Bot sends the day's script | Read it; `/redo [note]` for another story, or `/produce` |
| On `/produce` | Storyboard and package (sent as a document), then voice, frames, render and QC (~6 min) | Nothing |
| After render | The video arrives with Approve / Skip | Watch it; `/reshoot S03 [note]` redraws a frame, then Approve (~5 min) |
| On Approve | Posts to Instagram and Facebook (YouTube once its audit passes), replies with the links, then the posting kit for TikTok | Pin the comment question on each post; post to TikTok from the kit |
| 12:00 | Approval cutoff. An unapproved day publishes from the buffer or is skipped | Nothing |
| Audience evening | Staggered publish to all four; TikTok draft lands in your inbox | Tap Post in TikTok until automated |
| +24 h, +7 d | Stats pulled for every post | Nothing |
| 10:00 | Login check (`engine tokens`): Meta and YouTube | Nothing, unless a reminder arrives with steps |
| Sunday 10:00 | Weekly report in Telegram | 30-minute review; adjust prompts or formats |

Keep three approved videos in the buffer so exams or travel never break the streak.

## Commands (on the VPS, in /opt/content-engine)

```bash
docker compose ps                                   # what's running
docker compose logs -f worker                       # JSON logs
docker compose run --rm worker engine check         # settings + DB check
docker compose run --rm worker engine tokens --quiet   # Meta and YouTube login health, print only
docker compose run --rm worker engine run           # run today now
docker compose run --rm worker engine run --date 2026-10-12   # re-run a day (finished stages are skipped)
ssh -L 4200:localhost:4200 app@<vps>                # then open http://localhost:4200 for the Prefect UI
```

## When something breaks

**Daily run failed (Telegram alert).** Read the stage and error in the alert, then `docker compose logs worker`.
Fix the cause and re-run the day with `engine run --date <day>`. Finished stages don't run again.

**Dead-man's switch fired (no check-in by 09:00).** The worker isn't running or is stuck.
Run `docker compose ps` and restart with `docker compose up -d`. Then re-run the day.

**A platform failed after Approve.** The bot's reply says which and why, in the platform's words. Fix the
cause (often the Meta login: see the auth errors below), then send `/publish`. It posts only where the video
isn't live yet, so a retry never double-posts. `/publish instagram` retries just that one.
From a terminal: `engine publish` (or `engine publish --platform facebook`).

**"Stopped mid-upload, so it may already be live."** An upload was interrupted (the bot restarted, the network
dropped). Check the platform. If the Reel is there, send `/posted instagram` and it's never posted again. If it
isn't, send `/publish instagram` to post it again.

**A frame looks wrong (face drift, extra fingers, text in the image).** `/reshoot S03` draws it again;
`/reshoot S03 Fann faces the window, no text` adds your note to its prompt. Only that frame is paid for
(~$0.04); the rest come from the cache. The thumbnail is `/reshoot thumbnail`.

**Render QC failed.** The video still arrives, with the failing checks in its caption (loudness, length,
black frames), and you decide. A `/reshoot` of any frame renders it again. Renders and their build files
(the mix, the captions file, the filter graph) are under `WORK_DIR/runs/<day>/render_<n>/`.

**`BudgetExceeded`.** The daily cap stopped a run. Check `runs.llm_cost_usd` and the logs for a retry loop
before raising `DAILY_SPEND_CAP_USD`.

**`invalid_grant` / auth errors.** A platform token expired or was revoked. The 10:00 login check sends the
steps to Telegram: Meta from 3 days before its data access runs out, YouTube as soon as Google refuses the
login. Re-run `scripts/meta_tokens.py` or `scripts/youtube_auth.py` on your PC, copy the new lines into the
server's `.env`, then `docker compose up -d` to reload.

## Backups (Phase 5)

Nightly `pg_dump` to R2, kept 14 days. Test a restore once a month.
