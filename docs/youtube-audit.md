# YouTube API audit: what to put in the form

Form: https://support.google.com/youtube/contact/yt_api_form. Sign in first with the Google account that owns
the channel. Until the audit passes, every video the API uploads is locked to **private**; upload by hand in
YouTube Studio meanwhile (`YOUTUBE_UPLOAD_ENABLED=false`).

We don't need more quota: the default 10,000 units/day covers 4 uploads a week many times over. There is no
"audit only" option for a first audit, so pick the quota option in Section 1 and then **Default quota** in Section 5.

`<site>` below is your GitHub Pages address, e.g. `https://farhanko.github.io`.

## Before you open the form: collect the evidence

Save each screenshot as PNG. Take them on a desktop browser at normal zoom.

| # | File | How |
|---|---|---|
| 1 | `privacy.png` | `<site>/privacy.html`, full page. The "YouTube API Services", "Cookies" and "Revoking access" sections must be visible (use two shots if needed) |
| 2 | `homepage.png` | `<site>/`, showing the Privacy Policy link and the YouTube channel link |
| 3 | `terms.png` | `<site>/terms.html`, full page (this is the "Terms of Service Documentation") |
| 4 | `oauth-consent.png` | While running `scripts/youtube_auth.py`: the Google screen listing the three permissions |
| 5 | `oauth-done.png` | The terminal after the script finishes, showing `Done. Channel: The Enchanted Everyday` |
| 6 | `oauth-revoke.png` | https://myaccount.google.com/permissions with Enchanted Everyday Uploader listed (don't remove it) |
| 7 | `upload-*.png` | The upload flow: the Telegram approval message, the terminal/log of the upload, and the video in YouTube Studio (needs the uploader built and one private test upload) |

Optional but helpful for Section 6: an architecture diagram and a user-flow diagram (the README's pipeline
diagram is enough).

## Section 1: Request Type

- **Complete a compliance audit to request for additional quota**

## Section 2: Organization and Contact Information

- **Are you applying:** As an individual user
- **Full legal name:** your name as on your ID
- **Organization's legal name:** your own name again (you're applying as an individual)
- **Parent company:** leave empty
- **Primary website:** `<site>/`
- **Address:** your real postal address (Country, Street, City, State/Province, Postal code)
- **Category:** the closest to media / entertainment / content creation
- **Organization size / type:** Independent Developer/Sole Proprietor
- **Primary contact:** your name, theenchantedeveryday@gmail.com
- **Technical contact:** tick "Same as Primary Contact"
- **Business contact:** leave empty

## Section 3: Business Model and Google Contacts

**Describe your organization's work as it relates to YouTube:**

> The Enchanted Everyday (youtube.com/@TheEnchantedEveryday) is a one-person channel that publishes original
> illustrated short stories, "modern fairy tales for sleepless souls", as 45-90 second YouTube Shorts, four times a
> week. I write and produce every episode myself with my own tooling. The API client is a private tool that uploads my
> own finished videos to my own channel after I approve each one by hand, sets the title, description, thumbnail and
> playlist, and reads my own videos' view statistics so I can see which stories work. It has no other users, shows no
> YouTube content to anyone, and does not access any other channel's data.

- **Target audience:** Internal Users
- **Monetization:** Free service (we do not charge users)
- **Advertising questions:** Not applicable
- **Google / YouTube representative:** No, I do not have a Google representative
- **How did you first learn about the YouTube Data API?** YouTube for Developers documentation
- **Content Owner ID / Google Ads Customer ID:** leave empty

## Section 4: API Client Overview and Access Information

- **API Client name:** Enchanted Everyday Uploader
- **Contains "YouTube"?** No
- **Primary access URL:** `<site>/`
- **Privacy Policy URL:** `<site>/privacy.html`
- **Terms of Service URL:** `<site>/terms.html`
- **Publicly accessible?** No
- **Demo account fields:** don't put any password here. If a field is required, write in Special Instructions:

> This is a private command-line tool with no login page and no other users; it runs only on my own computer and
> signs in to my own channel through Google OAuth. The screenshots attached in Section 5 show the full flow:
> consent screen, upload, and the result in YouTube Studio.

- Tick the acknowledgment box only if the form insists; you're not giving credentials.

## Section 5: Use Cases and Quota Extension Details

- **How many project numbers:** 1
- **Google Cloud project number:** Cloud Console, project "YouTube Manager", the dashboard's Welcome card (digits
  only; not the project ID)
- **Use case:** Video Uploading & Account Management
- **Sign in with Google (OAuth)?** Yes
- **Derived metrics and data storage agreement:** tick it. The tool keeps view/like counts for its own videos to
  compare episodes over time; this agreement allows storing those stats for up to 36 months.
- **Expected API usage volume:**

> About 4 uploads a week (one a day at most). Per upload: one videos.insert, one thumbnails.set, one
> playlistItems.insert and one videos.update. Plus one videos.list and one channels.list call a day to read
> statistics for my own recent videos. Total stays well under the default 10,000 units per day.

- **Required evidence:** privacy (`privacy.png`), homepage (`homepage.png`), terms (`terms.png`)
- **Conditional evidence:** `oauth-consent.png`, `oauth-done.png`, `oauth-revoke.png`, and the `upload-*.png` shots
- **Endpoints:** tick
  - youtube.videos.insert
  - youtube.videos.update
  - youtube.videos.list
  - youtube.thumbnails.set
  - youtube.channels.list
  - youtube.playlists.list
  - youtube.playlistItems.insert
- **Total quota:** No change / Default quota (10k quota points)

## Section 6: Additional Evidence

Optional, but attach both: **Architecture Diagram** -> `docs/audit/architecture.png`, **User Flow Diagrams** ->
`docs/audit/user-flow.png`. Leave Other Supporting Materials empty.

## Section 7: Attestations

Tick every box. Pick your language. Read the whole form back once, then Submit.

## After submitting

- Google replies by email to theenchantedeveryday@gmail.com, sometimes with follow-up questions. Answer them in the
  same thread.
- When it passes, set `YOUTUBE_UPLOAD_ENABLED=true` in `.env`.
- If you change what the tool does with YouTube (e.g. start posting comments), tell YouTube before you ship it.
