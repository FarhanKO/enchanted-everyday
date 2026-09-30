# Open decisions

The architecture is settled (see `adr/`). These content choices are still open. **The niche blocks Phase 1.**

| Decision | Options | Default if undecided | Decide by | Choice |
|---|---|---|---|---|
| Niche | Any topic you can fact-check in a minute | none: blocks Phase 1 | Oct 4, 2026 | _open_ |
| Language | English (bigger audience, more competition) or Bangla (smaller, less crowded) | English | Oct 4, 2026 | _open_ |
| Voice | Your recorded voice, a clone of your own voice, or stock TTS | Your recorded voice | Oct 4, 2026 | _open_ |
| Visual style | Stock footage + code-drawn graphics, or add AI clips | Stock and graphics; AI clips capped | Oct 18, 2026 | _open_ |
| TikTok route | Inbox upload, manual posting, or a managed posting API | Manual until inbox upload is approved | Oct 25, 2026 | _open_ |

Once decided, set `NICHE`, `CONTENT_LANGUAGE`, `TRENDS_GEO` and `NICHE_RSS_FEEDS` in `.env`,
and record the choice here with a line on why.

## Niche checklist

A good niche for this pipeline:

- Claims can be checked against a primary source in about a minute (the critic pass and your approval depend on it)
- There's a steady news or trend flow, so the trend scan finds 20 items most days
- Stock footage and simple charts can illustrate it, with no need for other creators' clips
- You have a genuine view on it. YouTube's inauthentic-content policy demonetizes templated videos with no take
- It has 3-5 good RSS feeds (put them in `NICHE_RSS_FEEDS`)
