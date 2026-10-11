# YouTube channel setup: The Enchanted Everyday

Channel: <https://www.youtube.com/channel/UCFGoWuTaPJu1_c0HLP2Owpg> (@TheEnchantedEveryday).
Everything below is pasted by hand in **YouTube Studio** (studio.youtube.com). Work top to bottom; each section names
the Studio screen it goes in. Name decision: `decisions.md`, 2026-10-10.

## 1. Profile: Customization -> Profile

**Name:** `The Enchanted Everyday`

**Handle:** keep `@TheEnchantedEveryday`

**Description** (738 of the 1,000 characters allowed):

```
Modern fairy tales for sleepless souls.

A man sells his dreams to a shop that only opens at midnight. A train arrives for people running from a goodbye. A lie turns into a bird and will not leave. Short illustrated stories about ordinary people, strange worlds and very big feelings, told quietly, for the hour when you can't sleep.

Four new stories every week.

Every story stands on its own. Watch a few and you'll start to notice the same city: the Midnight Shop, the 12:07 train, the old tree beneath which people leave letters, and two strangers, Fann and Tina, whose paths keep almost crossing.

The stories, characters and direction are our own. The artwork and voices are made with AI-assisted tools.

Goodnight, sleepless soul.
```

**Links:** leave empty until the Instagram, TikTok and Facebook accounts exist, then add them with these titles:
`Instagram`, `TikTok`, `Facebook`. Put Instagram first: the first link is the one shown on the channel page.

**Contact info:** a dedicated business address, not your personal one. Optional; skip it if you don't have one.

## 2. Branding: Customization -> Branding

| Slot | Upload | Spec |
|---|---|---|
| Picture | Prompt A below (or `brand/references/tina/portrait_v2.jpg`, cropped) | 800 x 800 PNG/JPG, under 4 MB, shown as a circle |
| Banner | Prompt B below | 2560 x 1440, under 6 MB. Only the centre **1546 x 423** shows on every device |
| Video watermark | Prompt C below, background removed | 150 x 150 or larger, PNG, under 1 MB. Only shows on long videos, so it matters when the compilations start |

### How to run the prompts

Use Nano Banana (Gemini image) with the reference images attached, so the faces match the episodes. Attach the files
named in each prompt from `brand/references/`. Fann's portrait doesn't have his mustard scarf yet; the prompt adds it.
Generate 3-4 tries per slot and pick the one where both faces match the references.

### Prompt A: profile picture (Tina) · 1:1

Attach: `tina/portrait_v2.jpg`, `tina/sheet_v2.jpg`

```
Redraw the woman from the attached reference images as a square 1:1 channel profile picture. Keep her face exactly the same as in the portrait. Tina, a woman in her mid-twenties, slim, wavy black hair parted in the middle and falling just past her shoulders, large dark almond-shaped eyes with soft lashes, fair warm skin with rosy cheeks, a small beauty mark just below the left corner of her lower lip, wearing a rose-pink kurta with pale-blue piping and a long pale-blue striped dupatta draped over both shoulders.

Head and shoulders, centred, her face filling the middle of the frame so it still reads inside a small circle. She looks slightly past the viewer with a calm, curious half-smile, as if she just heard something no one else did. Behind her: a soft, out-of-focus night window with a single warm amber lamp glow on one side and deep midnight-blue on the other, a few floating dust motes catching the light. Nothing important near the corners.

Characters drawn with clean fine ink outlines and soft flat watercolour washes, gentle shading, large expressive dark eyes, soft rosy cheeks, set against a hand-painted gouache background with visible brush strokes, single warm practical light source glowing amber against deep midnight-blue shadows, rose and cream highlights, subtle film grain, quiet melancholic atmosphere, soft edges, painterly anime-inspired background art.

No text, no letters, no speech bubble, no border, no white corners, no circle frame, no watermark, not photorealistic, not 3D.
```

Alternative if you'd rather have an emblem than a face (no references needed):

```
A square 1:1 channel icon: a single tiny brass bell shaped like a crescent moon, hanging from a thin plum-coloured ribbon, glowing softly with warm amber light in the centre of a deep midnight-blue field. Large and simple enough to read at 48 pixels. Hand-painted gouache with visible brush strokes, a few floating dust motes, subtle film grain. No text, no letters, no border, no watermark, not photorealistic, not 3D.
```

### Prompt B: banner (Fann and Tina from behind, looking out over the city) · 16:9

Attach: `tina/sheet_v2.jpg` (it has her back view), `fann/portrait_v1.jpg` (for his hair). They're seen from behind,
so the scarf, the shirt and the dupatta carry who they are, not their faces.

```
A wide 16:9 painting for a YouTube channel banner, seen from behind two people. Late at night on a grassy hilltop beneath a huge ancient gnarled tree, an old wooden bench looks out over a sleeping city far below.

IMPORTANT LAYOUT: everything that matters sits inside one horizontal band across the middle of the image, the middle 30% of the height and the middle 60% of the width. The top 35% is only night sky, faint stars and the dark edge of the tree's leaves; the bottom 35% is only dark grass and small wildflowers in shadow. Nothing important near the edges.

Inside that central band:
- Two small figures sit on the bench, seen from directly behind, both looking out at the view. They sit at opposite ends of the bench with an empty seat between them, each alone with their own thoughts, not looking at each other.
- On the left, Fann: short thick black hair swept up and to the side, a light-blue collared cotton shirt with the sleeves rolled to the forearm, and a long mustard-yellow knitted scarf hanging down his back.
- On the right, Tina: wavy black hair falling just past her shoulders, a rose-pink kurta, and a long pale-blue striped dupatta draped over both shoulders and hanging down her back.
- The view: a sleeping city of small warm amber windows under a large pale moon, a slow river reflecting the moonlight, and a tiny lit train crossing a distant bridge. One window in the city glows a little brighter than all the others.

Characters drawn with clean fine ink outlines and soft flat watercolour washes, gentle shading, set against a hand-painted gouache background with visible brush strokes, detailed lived-in environment, warm amber city lights against deep midnight-blue shadows, rose and cream highlights, floating dust motes catching the moonlight, subtle film grain, quiet melancholic atmosphere, soft edges, painterly anime-inspired background art.

No text, no letters, no logo, no watermark, no faces visible, no character-sheet layout, not photorealistic, not 3D, no harsh neon.
```

The empty seat keeps them strangers, as the stories do. To seat them together instead, swap that line for:
`They sit side by side in the middle of the bench, close, shoulders almost touching.` That reads as a couple, which
the stories haven't established yet.

There is no lettering: YouTube prints the channel name right under the banner. Studio shows a "Preview on all
devices" box when you upload; if the figures get cut on mobile, drag the crop or regenerate.

**Chosen (2026-10-10):** a sunset version: Fann and Tina sitting close together under the old tree, from behind,
looking over a river valley. Nano Banana put them on the right and low, so the mobile view cuts Tina in half. Fix it
by attaching that image and running this edit:

```
Edit the attached image. Keep the exact same art style, colours, linework, the old tree, the valley, the river, the mountains, the sunset and both people exactly as they look now. Only change the framing, for a YouTube channel banner:
- Move the two seated people to the exact horizontal centre of the image, sitting close together on a small grassy ledge, still seen from behind.
- Make them smaller: the top of Fann's hair at about 38% of the image height from the top, and the bottom of their bodies and of Tina's dupatta at about 62%. Both whole figures must fit inside the middle third of the image height and the middle third of its width.
- Keep the river and the setting sun straight ahead of them, in the centre, above their heads.
- The old tree stays at the far left edge and the rocks at the far right edge, both cut off by the frame.
- The top third is only sky, clouds and branches; the bottom third is only grass, daisies and small rocks.
16:9, highest resolution available, no text, no letters, no watermark.
```

### Prompt C: video watermark · 1:1

```
A square 1:1 icon: a small brass bell shaped like a crescent moon, with a small ring at the top and a round brass clapper clearly hanging from its lower tip. Bold, thick dark-brown ink outline, flat warm gold watercolour fill with one cream highlight. Centred and filling about 70% of the frame, on a perfectly flat pure white background. No glow, no halo, no shadow, no gradient. Must read clearly at 40 pixels. No text, no letters, no border, not photorealistic, not 3D.
```

Then remove the white background (Canva's background remover, or remove.bg), save it as a transparent PNG at
300 x 300 or larger, and look at it at thumbnail size on a dark image before uploading. Display time: **Entire video**.

## 3. Home tab: Customization -> Layout

- **Featured sections:** add `Shorts`, then each playlist below as its own section, in the order listed.
- **Video spotlight:** skip until the first long-form compilation exists.

## 4. Playlists: Content -> Playlists -> New playlist

All **Public**, sorted **Date added (oldest)** so each one reads in order.

| Title | Description |
|---|---|
| Urban Fairy Tales | Something strange slips into an ordinary life in the city. What is happening? |
| Emotional Fairy Tales | An impossible offer, a strange rule, a what-if with a cost. What would you do? |
| Bedtime Fables | Gentle stories of the sky, the trees and small wonders. Nothing to be afraid of. |
| The Midnight Shop | Between 12:00 and 12:07, a shop opens that sells impossible things. Every story that passes through it. |
| Fann's Lost Dreams | Fann sold his dreams to pay what he owed. They didn't disappear. Start with the first one. |

Every episode goes into its universe playlist, plus The Midnight Shop or Fann's Lost Dreams when it touches them.

## 5. Channel settings: Settings -> Channel

**Basic info**
- Country of residence: Bangladesh (it decides monetization terms, so it has to be true)
- Keywords:

```
"modern fairy tales" "fairy tales for adults" "bedtime stories for adults" "short stories" "animated short stories" "illustrated stories" "sleep stories" "magical realism" "urban fantasy" fables storytelling "emotional stories" "cozy stories" "midnight stories" "The Enchanted Everyday"
```

**Advanced settings**
- Audience: **No, set this channel as not made for kids.** The audience is teens and adults. If one day a fable is
  aimed at children, mark that video "made for kids" on its own.

**Feature eligibility**
- Verify your phone number. It unlocks videos over 15 minutes (the bedtime compilations) and custom thumbnails.

## 6. Upload defaults: Settings -> Upload defaults

The pipeline writes each title, description and hashtags, so the defaults stay light.

| Field | Value |
|---|---|
| Title | empty |
| Description | empty |
| Visibility | Private (you switch it to Public or Scheduled after a last look) |
| Tags | `modern fairy tale, short story, animated story, bedtime story, magical realism, The Enchanted Everyday` |
| Category | Film & Animation |
| Video language / title and description language | English |
| Comments | On; "Hold potentially inappropriate comments for review" |
| Show how many viewers like this video | On |

## 7. With every upload (until API uploads are approved)

- Paste the episode's `youtube_title` and `youtube_description` from its package.
- Add it to its playlists (section 4).
- **Related video:** point each Short at the previous episode it connects to, so viewers can follow the thread.
- **Altered or synthetic content:** answer Yes only if the video shows realistic people, places or events that someone
  could mistake for real. The illustrated style usually doesn't need it; the channel description already discloses the AI
  artwork and voices.
- Leave "Allow remixing" on; Shorts remixes are free reach.
