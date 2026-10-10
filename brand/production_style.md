# Production style

How every episode looks, moves, sounds and is packaged. Visual, voice and sound agents receive this file.
The two reference images are the two poles of one universe, not two styles.

## 1. Look

| Pole | Reference | Palette | Light | Story function |
|---|---|---|---|---|
| **Night** | Girl asleep in a lamp-lit bedroom | Midnight blue, amber, rose, warm cream | One warm practical (lamp, window, jar) against deep blue shadow; floating dust motes | Intimacy, loneliness, memory, regret, private thought |
| **Day** | Giant tree on a cliff above the sea | Cobalt sky, luminous greens, turquoise sea, gold sun | Hard bright sunlight, dappled shade, towering sunlit cumulus | Wonder, childhood, renewal, hope, being small in a beautiful world |

### Rendering: characters vs. environments

The look is a deliberate blend:

- **Characters:** clean fine ink outlines, soft flat watercolour washes, gentle shading, large expressive dark eyes,
  soft rosy cheeks. This matches the approved references in [`references/`](references/).
- **Environments:** hand-painted gouache with visible brush strokes, and each pole's palette and light.

Characters read crisp and graphic in front of painterly, atmospheric backgrounds. Outlines belong to people, never to
the background.

### Style block

The locked prompt fragments live in [`style.toml`](style.toml): one style block per pole, the negative prompt,
and the video-motion suffix. **Agents never write them.** Agents write only the shot-specific part of a prompt
(composition, action, framing, emotion). Code then appends the characters' and location's locked descriptors and
the style block verbatim (`engine/prompting.py`), so every frame gets identical style and identity text.

### Rules

- **Never write an artist's, studio's or franchise's name in a prompt.** Describe the attributes instead. This is a
  copyright, policy and brand-identity rule, and validation rejects prompts that break it.
- **Human scale:** put a small figure against a large tree, city, sky or train to make the emotion visible.
- **Meaningful props:** tea, flowers, letters, clocks, doors, windows, trains, trees and photographs carry story weight.
- **Composition for vertical:** keep the subject in the centre 60% of the frame. The top 12% and bottom 25% are UI safe zones (captions, buttons).
- **One light story per shot:** a warm source in the night pole, and the sun's direction in the day pole.

## 2. Motion

Restraint is the brand. Slow drift, rain, curtains, steam, fireflies, train lights and breathing are enough.

- **Default `still_drift`:** the image is animated in code with a slow 4-8% push-in or pull-out, a slow pan, or 2-layer parallax.
  This costs nothing and keeps faces stable.
- **`ai_clip`:** an image-to-video model is used for at most **2 hero shots** per episode, where real motion matters
  (a jar glowing alive, waves under the tree). Clips of 3-5 s. The video prompt describes camera and environment motion only;
  faces barely move.
- **Overlays** (licensed loops, composited in code): rain on glass, falling rain, fireflies, dust motes, steam, film grain,
  light leak.
- **Transitions:** slow crossfades (0.6-1.0 s) or a dip to black before the landing. No whip pans, zooms or glitch effects.

Every video prompt gets the `video_suffix` from `style.toml` appended in code.

## 3. Character consistency system

Faces drifting between shots is the most common failure in AI-illustrated stories. Six layers handle it:

1. **Locked descriptors.** Each character has one descriptor string (age, build, hair, face, wardrobe, colour anchor).
   Code inserts it verbatim into every prompt that shows them. Agents reference characters by id and never re-describe them.
   The fixed cast (Fann, Tina, the Shopkeeper) lives in [`cast.toml`](cast.toml): same face and same outfit in every
   episode, and the cast descriptor overrides whatever a storyboard writes.
2. **Colour and silhouette anchors.** Every character gets one signature colour item and one prop (Fann's mustard scarf,
   Tina's rose-pink kurta and pale-blue dupatta, the Shopkeeper's plum cardigan and gold round spectacles). They're
   readable even when the face is small or turned away.
3. **Reference sheets.** Before a character's first episode, generate a turnaround sheet (front, three-quarter, side) and an
   expression sheet on a neutral background. Approve one canonical image, store its URI in `bible_entries.reference_uris`,
   and condition every later shot on it (reference-image or edit mode).
4. **Supporting characters.** Characters outside the cast are drawn from their storyboard descriptor alone, with no
   reference image yet. Make them easy to tell apart from the leads, because a model conditioned on Fann's or Tina's
   reference tends to copy that face onto everyone in the frame:
   - a clearly different age, build or hairstyle (e.g. grey hair, a bob, a beard, a child, an elder)
   - their own colour anchor; never mustard-yellow, or rose-pink with pale blue, which belong to the leads
   - when a lead and a stranger share a shot, place the stranger further back or partly turned away

   Before the episode renders, generate one plain-background portrait of each supporting character and condition
   their later shots on it, so they at least stay consistent within the episode.
5. **Shot design.** Prefer medium-wide shots, silhouettes, backs and hands when a close-up face isn't essential.
   No more than 2 face close-ups per episode.
6. **QC.** A vision check compares each frame with the character's reference image (hair, wardrobe, colour anchor, age).
   Frames that fail are regenerated before render. Recurring entities (the Shopkeeper, the Old Tree, the Midnight Shop)
   are shared across all episodes.

## 4. Narration

- **Voice:** intimate, calm, low energy, emotionally present. A secret told at 2 AM, not an announcement.
- **Pace:** 115-125 words per minute, slower than conversation.
- **Pauses:** after the impossible statement (hook), before the reveal, and before the final line. Pauses are scripted
  (`pause_after_s`) and rendered as real silence.
- **Point of view:** third person, with an occasional close first-person line.
- **Who speaks:** each episode is narrated, mixed or dialogue (story bible, "Story types and who speaks"). Every line
  names its speaker, and each speaker has a fixed voice in [`voices.toml`](voices.toml): the narrator is always the
  same voice, and so are Fann, Tina and the Shopkeeper.
- **Delivery notes per line:** used by a human narrator, or mapped to TTS style controls.
- **Recording (own voice):** a quiet room with soft furnishings, phone or mic 15-20 cm away, slightly off-axis, 2 takes per line,
  no music while recording. The pipeline handles noise reduction and loudness.
- **Loudness:** final mix at -14 LUFS integrated, true peak -1 dBTP. Narration sits 8-12 dB above the music bed.

## 5. Music and sound

| Layer | Use | Avoid |
|---|---|---|
| Music | Felt or soft piano, distant strings, restrained pads, subtle magical tones (celesta, glass) | Trailer swells, constant crescendos, music that tells the viewer how to feel |
| Ambience | Rain, room tone, wind, birds, trains, street ambience, kettle steam | Loops that overpower the voice or repeat obviously |
| Silence | A real beat before a reveal or the final line | Filling every second |

**Signature ending:** the final frame holds about 3 seconds; a single soft brass bell chime (the Shopkeeper's moon
bell) plays, and the narrator says "Goodnight, sleepless soul." barely above a whisper. Every episode, every mode.
Code adds both after the script's landing ([`sound.toml`](sound.toml), `[signature]`).

**Character sounds:** each recurring character has a sound heard where they first appear and a short musical motif
laid under that moment: Fann hums three falling notes (low felt piano); Tina's dupatta rustles (a music box answers
with four rising notes); the Shopkeeper's moon bell rings. Details in [`sound.toml`](sound.toml).

Music cues are scripted per episode (`enter`, `swell`, `thin`, `silence`, `resolve`, `out`). All music and SFX must be
licensed for commercial use, with the license stored on the asset row.

## 6. Subtitles

The brand is calm, so captions are phrase-level, never bouncing word-by-word.

- **Chunks:** 2-6 words, following natural speech phrases; at most 2 lines, 26 characters per line
- **Font:** Lora SemiBold (SIL Open Font License), 64 px at 1080x1920
- **Colour:** warm cream `#F6EEDF`, with a soft shadow (`#1A1530`, 60% opacity, 6 px blur). No box, no outline
- **Emphasis:** the one key word in a line can turn soft gold `#F2C66D`. At most one per caption
- **Position:** centred, baseline at 72% of frame height, inside the safe zone
- **Motion:** 150 ms fade in and out. Captions follow word timestamps from the voice track
- Silence beats show no caption, so the pause is visible as well as audible

## 7. Thumbnail and title

- **Thumbnail:** one face or one object, one readable emotion, one strong light/dark contrast, and 0-4 words of text in Lora.
  The first frame of the video doubles as the cover frame.
- **Title:** simple premise + unanswered question, at most 60 characters for Shorts.
- **Alternate titles:** write 2 for A/B or hook testing.

## 8. Disclosure

The artwork is AI-assisted, so every post discloses it: YouTube's altered or synthetic content setting where it applies,
Instagram's and TikTok's AI labels, and a line in each description:
> Story and direction by [channel]. Illustrated with AI-assisted artwork.
