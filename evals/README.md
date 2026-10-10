# evals

The golden-set eval catches prompt regressions before they reach a daily run.

- **Golden set:** every episode in `stories/*/episode.json`. Only episodes you've approved go there, so the set grows
  as the channel does. It starts with s000. The plan's target is 20.
- **What runs:** for each golden episode, the script writer writes a fresh script from the episode's story card, and
  the critic reviews it. The critic's role prompt (`engine/llm/prompts/critic.md`) is the rubric: the seven core rules,
  the five craft rules, and the production style.
- **What's recorded:** for each episode, whether the script met its contract, how many repairs it needed, the critic's
  verdict and issue counts, words and seconds. Results go to `results/<timestamp>-<prompt version>.json`.
- **The rule:** bump `PROMPT_VERSION` in `engine/llm/prompts/__init__.py` with any role-prompt change, then run
  `python -m engine eval`. The command exits non-zero if the pass rate drops below the previous run, and that
  blocks the change.

It calls the real model, roughly $0.10-0.25 per golden episode, so it never runs in CI. `--max-usd` caps a run
(default $3).

Add an episode to the golden set by approving it and saving its `episode.json` (and `python -m engine episode`'s
rendered `episode.md`) under `stories/<slate id>-<slug>/`.
