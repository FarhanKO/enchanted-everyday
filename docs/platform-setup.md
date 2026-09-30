# Platform setup checklist

Start every item on **Oct 5, 2026**. Approvals are the slowest part of the build, and the YouTube audit
has no published turnaround. Tick items off here as they land.

## YouTube

- [ ] Create the channel and a dedicated Google Cloud project; enable YouTube Data API v3
- [ ] Create an OAuth client; set the consent screen to **In production** (in Testing, refresh tokens expire after 7 days)
- [ ] Create an API key for trend search (`YOUTUBE_API_KEY`), restricted to YouTube Data API v3
- [ ] Submit the YouTube API audit and quota form. API uploads stay private until it passes
- [ ] Until then, upload the approved file by hand in YouTube Studio (`YOUTUBE_UPLOAD_ENABLED=false`)
- [ ] Set `status.containsSyntheticMedia` whenever visuals or voices are realistic AI

## Instagram and Facebook

- [ ] Switch Instagram to a professional account; create a Facebook Page and link the two
- [ ] Create one Meta app with Instagram and Page publishing. Standard Access covers your own accounts without App Review
- [ ] Publish `docs/privacy-policy.md` on GitHub Pages; put its URL in the app settings; switch the app to **Live**
  (Development-mode posts are visible only to app roles)
- [ ] Post a test Reel and confirm it from an account with **no** app role
- [ ] Serve videos from a public R2 URL; set `is_ai_generated` when it applies
- [ ] Stay under 30 API-published Reels per Page per 24 hours

## TikTok

- [ ] Create a TikTok for Developers app with Login Kit and the Content Posting API
- [ ] Request the `video.upload` scope. Drafts land in your TikTok inbox and you tap Post
- [ ] Until it's approved, post manually from your phone
- [ ] Don't plan on public Direct Post: unaudited apps post privately, and a tool for your own accounts won't pass the audit

## Telegram

- [ ] Create the bot with @BotFather; put the token in `TELEGRAM_BOT_TOKEN` on the server only
- [ ] Get your numeric user ID (e.g. from @userinfobot) into `TELEGRAM_OWNER_ID`. The bot ignores everyone else

## Infrastructure

- [ ] Hostinger KVM 2 (Ubuntu 24.04), SSH key added in the panel
- [ ] Run `scripts/provision_vps.sh`, then confirm `ssh app@<vps>` works
- [ ] Cloudflare R2 bucket + API token (object read/write on that bucket only); public access or a custom domain for `R2_PUBLIC_BASE_URL`
- [ ] Anthropic API key with a monthly spend limit set in the Console
- [ ] Pexels API key
- [ ] healthchecks.io check: schedule 05:00 Dhaka, grace until 09:00, alerts to Telegram; URL into `HEALTHCHECK_PING_URL`
- [ ] GitHub repo secrets for deploy: `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY` (a deploy-only key), `VPS_KNOWN_HOSTS`
