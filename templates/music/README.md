# Music library

Music follows the story. The storyboard gives every shot a mood, and the render plays one track for each run of
shots with the same mood, crossfading where the story turns (`engine/media/music.py`):

| Mood | Where | Tracks here |
|---|---|---|
| `calm` | Setting the scene, quiet nights | Midvinter, Sleep, The Long Way Home, Reverie, First Snow |
| `wonder` | Magic, discovery, sunlit dreams | Echoes Of Home, Amberlight, Reawakening, Hymn to the Dawn, Castles in the Sky |
| `mystery` | The strange thing appears | In Search Of Solitude, Beyond These Walls, Shadows and Dust, Sanctuary |
| `tension` | Consequences piling up | Intervention, A Dragon's Lullaby, Unraveling, Signal to Noise |
| `sorrow` | Loss, longing | Hiraeth, Penumbra, The Long Dark, She Moved Mountains |
| `warm` | The ending, hope | Moonlight, A Kind Of Hope, Solace, Static |
| `playful` | Light bedtime moments | Childhood, Eidolon |
| `none` | Where music would be too much | (silence: voice and ambience) |

Many tracks also carry a second mood (Solace is warm, calm and wonder), so each mood has more to choose from.

**How a track is picked:** first one not heard in the last ~4 episodes (the render reads the music earlier renders
used), then one whose strongest mood it is, then one that suits the episode's look (night or day). So the same
music doesn't play under every video. Each section is levelled to the same loudness, starts from the top of its
track, fades out under the bell and the signature line, and sits well under the voice: about 8 dB below it in the
pauses and 13 dB while someone speaks. An episode whose storyboard says `none` throughout has no music at all.

## Credits: every post names its music

All 28 tracks are by Scott Buckley, under CC BY 4.0 (free for commercial use with credit; terms:
https://www.scottbuckley.com.au/library/using-this-music/). Downloaded 2026-10-12. The render records each track's
`credit` line, and the posting kit adds it to the YouTube description and the Instagram, Facebook and TikTok
captions. On YouTube the credit must be in the description: his Content ID system claims videos without it. If a
claim still appears, use his release guide: https://www.scottbuckley.com.au/library/copyright-claims-release/

## Adding a track

1. Put the file here (mp3, wav, m4a or flac). Audio files are git-ignored; keep your own copy.
2. Add an entry to `library.toml`. **No license, no use**: a track without one is skipped.

```toml
[[track]]
file = "felt_piano_night_01.mp3"
title = "Felt Piano Night"
moods = ["calm", "sorrow"]  # strongest first: calm wonder mystery tension sorrow warm playful
pole = "night"              # night | day | any
license = "CC BY 4.0, example.com/track, downloaded 2026-10-12"
credit = 'Music: "Felt Piano Night" by Someone – released under CC-BY 4.0. example.com'
gain_db = 0                 # optional, on top of the automatic levelling
```

## What fits the brand

Felt or soft piano, distant strings, restrained pads, celesta, harp or glass tones; slow, no drums, no build-ups
in the opening minute (the render uses the top of each track) (`brand/production_style.md` §5). Instrumental only.

## Where licensed music comes from

Check each track's own terms before adding it: commercial use, use outside YouTube (Instagram, Facebook, TikTok),
and the credit it needs. Libraries that register tracks with Content ID can still trigger a claim; keep the license
text in `license` so you can dispute it.
