# ADR 0003: One human approval tap before anything posts

**Status:** accepted, 2026-09-30

## Context

Fully automatic posting is technically possible. The risks are wrong facts, copyright problems,
undisclosed AI media and YouTube's inauthentic-content policy, which demonetizes mass-produced,
templated videos with no genuine take.

## Decision

Every render goes to the owner on Telegram with its captions and sources. Only **Approve** leads to publishing.
**Redo** re-renders, and **Skip** drops the day. No answer by 12:00 means the day publishes from the approved
buffer or is skipped. It never publishes the unapproved render.

## Why

- Catches factual and taste errors that the critic pass misses
- Keeps the channel authentic: the owner's voice and judgement are in every video
- Costs about 5 minutes a day, inside the 10-minute budget
- Success criterion: **zero posts that skipped approval**, enforced in code (publish requires an `approvals` row
  with `decision='approve'`) and tested

## Costs

Posting depends on the owner being reachable. The three-video buffer and the noon cutoff mean that costs a
buffered video, never a bad post.
