# Platform setup checklist

Start every item on **Oct 5, 2026**. Approvals are the slowest part of the build, and the YouTube audit
has no published turnaround. Tick items off here as they land.

## YouTube

- [x] Create the channel and a dedicated Google Cloud project; enable YouTube Data API v3
  (@TheEnchantedEveryday; Cloud project "YouTube Manager")
- [x] Create an OAuth client; set the consent screen to **In production** (in Testing, refresh tokens expire after 7 days)
  (Desktop client; app "Enchanted Everyday Uploader"; `scripts/youtube_auth.py` fills `YOUTUBE_REFRESH_TOKEN`)
- [x] ~~Create an API key for trend search~~ Not needed: the fiction niche dropped the trend scan
- [x] Submit the YouTube API audit and quota form ([youtube-audit.md](youtube-audit.md) has every answer). API uploads stay private until it passes
  (submitted 2026-10-11; replies go to theenchantedeveryday@gmail.com)
- [ ] Audit passes: set `YOUTUBE_UPLOAD_ENABLED=true`
- [ ] Until then, upload the approved file by hand in YouTube Studio (`YOUTUBE_UPLOAD_ENABLED=false`)
- [ ] Set `status.containsSyntheticMedia` whenever visuals or voices are realistic AI

## Instagram and Facebook

- [x] Switch Instagram to a professional account; create a Facebook Page and link the two
  (@enchantedeveryday.tales, Page "The Enchanted Everyday")
- [x] Create one Meta app with Instagram and Page publishing. Standard Access covers your own accounts without App Review
  ("Enchanted Everyday Uploader"; `scripts/meta_tokens.py` fills the three `META_*` values in `.env`)
- [x] Publish `docs/privacy-policy.md` on GitHub Pages; put its URL in the app settings; switch the app to **Live**
  (Development-mode posts are visible only to app roles).
  Live at <https://farhanko.github.io/enchanted-everyday/privacy.html>
- [ ] Re-run `scripts/meta_tokens.py` before **2027-01-08**: the Page token never expires, but Meta's 90-day
  data-access window does unless the token is refreshed
  (the 10:00 login check reminds you in Telegram, with the steps, from 3 days before; access ends
  2027-01-09 02:43 Dhaka)
- [ ] Post a test Reel and confirm it from an account with **no** app role: set `DRY_RUN=false`, approve a
  video, and open the links the bot sends back
- [x] Upload the file straight to Meta (resumable upload, no public URL or R2 needed); `is_ai_generated` set on
  every Reel (`engine/publishers/meta.py`)
- [ ] Stay under 30 API-published Reels per Page per 24 hours

## TikTok

- [ ] Create a TikTok for Developers app with Login Kit and the Content Posting API
- [ ] Request the `video.upload` scope. Drafts land in your TikTok inbox and you tap Post
- [ ] Until it's approved, post manually from your phone
- [ ] Don't plan on public Direct Post: unaudited apps post privately, and a tool for your own accounts won't pass the audit

## Telegram

- [x] Create the bot with @BotFather; put the token in `TELEGRAM_BOT_TOKEN` on the server only
- [x] Get your numeric user ID (e.g. from @userinfobot) into `TELEGRAM_OWNER_ID`. The bot ignores everyone else

## Infrastructure

- [ ] A server with Ubuntu 24.04 and your SSH key added in the panel: Oracle Cloud Always Free
      (VM.Standard.A1.Flex, ARM; upgrade the account to Pay As You Go so an idle free server isn't
      reclaimed) or a paid VPS such as Hostinger KVM 2
- [ ] Run `scripts/provision_vps.sh`, then confirm `ssh app@<vps>` works
- [ ] Cloudflare R2 bucket + API token (object read/write on that bucket only); public access or a custom domain for `R2_PUBLIC_BASE_URL`
- [ ] Anthropic API key with a monthly spend limit set in the Console
- [ ] Image model API key (provider still open, see `decisions.md`)
- [ ] healthchecks.io check: schedule 05:00 Dhaka, grace until 09:00, alerts to Telegram; URL into `HEALTHCHECK_PING_URL`
- [ ] GitHub repo secrets for deploy: `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY` (a deploy-only key), `VPS_KNOWN_HOSTS`
