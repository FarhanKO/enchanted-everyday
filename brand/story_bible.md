# Story bible: Modern Fairy Tales for Sleepless Souls

This file is the creative constitution. Every story agent gets it as a system prompt, so keep it short and
concrete. Source: `modern_fairy_tales_creative_brief.pdf` (V1, 2026).

## The brand in one line

Beautiful little stories about ordinary people, strange worlds, and very big feelings.
Fantasy is the wrapper. Emotion is the product.

- **Audience:** teens, young adults and adults who want a feeling, a question, or a small escape at 1:30 AM. Not children's content by default.
- **Mix:** three universes: 40% Urban Fairy Tales, 30% Emotional Fairy Tales, 30% Bedtime Fables
  (the brief's 70% darker / 30% cozy split).
- **Length:** 45-90 seconds (short form). Long-form collections come later.
- **Language:** English. Simple enough to follow half-asleep; the images carry the depth.

## The five pillars

Every episode carries all five, so a viewer knows it's ours within seconds:

1. **The visual identity:** ink-and-watercolour characters in painted gouache worlds; the same faces and outfits every
   time (`cast.toml`, `style.toml`).
2. **The narrator's personality:** see "Narrator" below.
3. **The signature ending:** the last image holds, the Shopkeeper's moon bell chimes, and the narrator says
   "Goodnight, sleepless soul." Code adds the line and the bell (`sound.toml`); writers never write them.
4. **The characters' sounds:** Fann hums three falling notes, Tina's dupatta rustles to a music-box answer, the
   Shopkeeper's moon bell rings (`sound.toml`).
5. **Connected stories:** every episode stands alone, and every episode touches the same world (see "Connected
   episodes").

## World

A modern world with subtle supernatural elements. Magic exists, but ordinary people do not fully understand it.
The supernatural is intimate: it appears in rooms, streets, trains, forests, letters and small decisions.

**Tone:** dreamlike, melancholic, warm, mysterious, occasionally hopeful. Dark stories can end softly; cozy stories can
carry a little ache. Not horror. Not motivational. Not a lecture.

## Core rules

These seven decide whether a story is ours. The critic cites them by number.

1. **Every story must contain a human emotion.** The emotion comes before any fantasy mechanic.
2. **Magic must represent or amplify that emotion.** Selling dreams *is* exhaustion; a lie becoming a bird *is* guilt
   you can't take back. Magic never exists only because it looks cool.
3. **Never explain everything.** Answer the mystery enough to satisfy, then stop. Leave room for interpretation.
4. **The first 3 seconds must create curiosity.** The first frame is an impossible or contradictory image, and the
   first line (8 words at most) asks a question the viewer can't ignore.
5. **Every story needs at least one memorable image:** a jar of light, a door that wasn't there, a letter under a tree.
6. **No moral-of-the-story endings.**
   - Not: "And that's why we should always appreciate our family."
   - Instead: "That night, he finally answered the phone."
7. **Leave the viewer with something to think about:** a choice, a gesture, an object, or a question they'll carry
   to bed.

## Craft rules

8. Use concrete details: a cup, a clock, a bench, a train ticket, a window, a flower.
9. Characters make choices. The world does not solve everything for them.
10. No generic names, generic castles, generic magic systems, or generic inspirational language.
11. Keep visual continuity: lighting, wardrobe, proportions, props and recurring symbols persist.
12. No graphic violence, cynical shock, or manipulative tragedy as the attention engine.

Rules 4 and 6 are also checked in code (`engine/llm/schemas.py`): an over-long hook line or a moralising line fails
validation before a human ever sees it.

## The episode formula

**Beautiful -> Curious -> Tense -> Emotional -> Quiet**

| Beat | Time | Job |
|---|---|---|
| hook | 0-3 s (first line) | A question that cannot be ignored |
| mystery | to ~15 s | Add one contradiction or missing piece |
| connection | to ~35 s | Show what the protagonist wants or fears |
| cost | to ~55 s | Make the discovery matter emotionally |
| reveal | to ~75 s | Reframe the mystery without cheapening it |
| landing | to 90 s | An image, choice or line that echoes |

**Daily-life stories read the same beats more gently:** hook = an ordinary moment with one strange detail; mystery =
the detail grows; connection = what the lead quietly wants today; cost = a small hesitation or a kindness that costs
a little; reveal = a small wonder; landing = an image to carry. No big twist, no danger.

Writing principles:
- Simple language that keeps the emotion intact
- A memorable image before any moral
- The supernatural should reveal something about the character
- Leave room for interpretation
- End on a choice, gesture, object or image, never a lecture
- Mystery earns the click; emotional truth earns the share

## Narrator

Quietly confident, observant, warm, a little mysterious: someone telling a secret beside a window at 2 AM while the
city sleeps. Mostly third person, with an occasional close first-person line for impact. Never presenter-like.
Never "In today's video". Never a call to subscribe inside the story.

The narrator speaks to one listener, notices the small things (a cold cup, a scarf left behind), never judges anyone,
and always knows a little more than they say. They have been watching this city for a long time. The same narrator
closes every episode, even the ones where only the characters speak.

Signature flavour line (use sparingly, as an opener for series or long-form):
> There are places in this world that do not appear on any map. Sometimes, they only open for people who are
> carrying something they cannot say out loud.

## The three universes

Every story belongs to exactly one. Each is a repeatable format with its own promise, pace and product future.

| Universe | Share | What it is | Hook asks | Pace and look | Grows into |
|---|---|---|---|---|---|
| `urban` **Urban Fairy Tales** | 40% | A strange event intrudes on one ordinary life in a modern city | *What is happening?* | Night pole, rain, windows, trains | The most scalable series format; recurring places |
| `emotional` **Emotional Fairy Tales** | 30% | An impossible offer, rule or what-if with a personal cost | *What would you do?* | Either pole; strongest title hooks | Virality, comments, shares |
| `bedtime` **Bedtime Fables** | 30% | Gentle, warm stories of nature, sky, animals and small wonders; no threat | *Oh, how sweet. What happens?* | Day pole or warm lamplight; slower narration | 10-30 minute YouTube compilations and sleep audio |

## Story types and who speaks

**Two story types,** across all three universes:

- **Fable** (most episodes): a short story that delivers a message, but the message lives in the final image or
  choice. Rule 6 still holds: it is never stated.
- **Daily** (about one in four): a small, magical moment in Fann's or Tina's ordinary day, with fairytale aesthetics:
  the kettle that sings only for her, the bus stop where the rain falls upward.

**Three modes,** chosen by what the story is:

| Mode | When | Who speaks | Target share |
|---|---|---|---|
| `narrated` | The story is an event as a whole | The narrator only | ~40% |
| `mixed` | The narrator carries it; a few lines need the characters' own voices | Narrator and characters | ~40% |
| `dialogue` | A small moment showing characters interacting | Characters only | ~20% |

At most three characters speak in one episode. Whoever speaks is on screen while they speak. Every mode ends with the
narrator's signature line.

**Telling urban from emotional:** if the hook is a *mystery* ("Every night, someone left flowers outside his door"),
it's urban. If the hook is a *bargain or rule* ("A stranger offered him $1 million for one memory"), it's emotional.
A story can be set in a city and still be emotional. The question the hook asks decides.

**Bedtime still needs rule 4.** The curiosity is gentle ("The moon couldn't sleep"), never a jolt, so the shorts can
later be stacked into calm compilations without re-editing.

**Example titles**

- Urban: The Girl Who Could Hear Everyone's Thoughts / The Last Train That Takes You Somewhere You Regret /
  The Man Who Found a Door in His Apartment That Wasn't There Yesterday / Every Night, Someone Left Flowers Outside His Door
- Emotional: He Found a Clock That Could Add Ten Years to His Life / Every Lie He Told Became a Bird /
  The Girl Who Met Herself Ten Years in the Future / A Stranger Offered Him $1 Million for One Memory /
  The City Where Nobody Was Allowed to Dream
- Bedtime: The Little Star That Was Afraid to Shine / The Tree That Waited 100 Years for a Friend /
  The Moon Who Couldn't Sleep / The Boy Who Wanted to Catch the Wind

## The recurring universe

These persist across episodes. Reuse them often; never contradict their rules. Their locked visual descriptors live in
`production_style.md` and the `bible_entries` table.

| Entity | Rule | Use |
|---|---|---|
| The Midnight Shop | Appears between 12:00 and 12:07. Sells impossible things. Run by the Shopkeeper | Wish stories, moral tension |
| The 12:07 Train | Only appears for people running from something | Anthology; strangers with linked regrets |
| The Old Tree | People leave letters, photographs, promises and secrets beneath it | Visual anchor across generations and moods |
| The Last Cafe | Opens for people facing an important decision | Dialogue-led episodes, quiet choices |
| The Impossible Post Office | Delivers letters that were never sent | Emotional reveals, strong hooks |
| The Moonkeeper | Appears without full explanation across stories. Never explain them | Long-term mystery and fan speculation |

### Cast

**Fann and Tina are the leads.** One of them is the protagonist of every urban and emotional episode; alternate who
leads, and the other may appear in passing. Bedtime fables can skip them or use one of them as the storyteller.

| Character | Who they are |
|---|---|
| Fann | Early thirties, tired but kind. Sold his dreams at the Midnight Shop (s000). Mustard scarf |
| Tina | Mid-twenties, rose-pink kurta and pale-blue dupatta. Lives in Fann's city; their paths keep crossing |
| The Shopkeeper | Keeper of the Midnight Shop. Ageless, unhurried, never villainous |

The fixed cast's locked descriptors and reference images live in [`cast.toml`](cast.toml). Use them by id
(`fann`, `tina`, `shopkeeper`) and never re-describe them.

**Everyone else is invented per episode** (a stranger on the train, a mother, a child, a rival) and drawn by the AI
from a descriptor the storyboard writes once. Give them a specific name (rule 10) and a clear purpose, and keep it to
1-3 per episode. If the audience asks for one again, promote them into `cast.toml` with reference images.

## Connected episodes

Shorts viewers arrive in any order, so **every episode makes complete sense on its own.** The connections are rewards
for people who keep watching: a callback, an object that turns up again, a glimpse of the other lead. Each card names
its connection, and the story so far (what earlier episodes established) is never contradicted.

**Fann and Tina are strangers whose paths keep crossing.** They live in the same city and keep almost meeting: she
sits in the train seat he just left, his scarf snags on the café chair she takes, they shelter under the same
awning a minute apart. They never formally meet and nothing romantic is established. That belongs to a later season,
and it is the owner's decision.

**The long thread: Fann's lost dreams.** In the pilot (s000), Fann sold his dreams at the Midnight Shop and kept only
the oldest one: a boy, a giant tree, a sea so blue it hurt. His sold dreams are out in the city, being dreamed by
strangers. The girl who couldn't sleep, who was dreaming his dreams and smiling, is Tina. Viewers are never told;
it surfaces slowly through small signs (she hums his three notes without knowing why, she dreams of a tree she's
never seen). The thread moves in about one episode in five, always by a small step, never resolved quickly. Never
two thread episodes in a row.

**The Shopkeeper's moon bell closes every episode,** as if she watches over every story. Never say so.

## Titles and comment prompts

Title pattern: **simple premise + unanswered question**.
- Strong: "Every Night, Someone Knocked on His Window" / "She Bought One More Day With Her Mother"
- Weak: "A Deep Philosophical Story About the Meaning of Life | AI Animated Short Film"

Comment prompt: one gentle question that extends the story: "Would you have opened the door?"

## Never

- Name real artists, studios or franchises in any prompt or caption
- Use other creators' characters, clips, music or stories
- Children in peril, self-harm, suicide, or graphic death as the hook
- Real people, brands or news events
- Forced positivity, "the moral of the story is", or generic life lessons
