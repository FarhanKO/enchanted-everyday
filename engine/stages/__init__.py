"""Pipeline stages and the order the flows run them in.

The daily run writes and reviews the story; production only starts once the owner has the script,
so a script they'd reject never costs a storyboard. Every stage of a day shares that day's run row,
so production stages read the story stages' outputs.

Built so far (Phase 1). Coming next, by phase:
  Phase 2: assets, render, approve (production; the owner's voice note starts it)
  Phase 3: publish
  Phase 4: analytics (separate scheduled flow)
"""

from engine.stages import deliver, discovery, idea, story
from engine.stages.base import StageContext, StageFn, run_stage

STAGES: dict[str, StageFn] = {
    "discovery": discovery.run,
    "idea": idea.run,
    "script": story.script,
    "critic": story.critic,
    "deliver_script": deliver.deliver_script,
    "storyboard": story.storyboard,
    "package": story.package,
    "deliver_package": deliver.deliver_package,
}

DAILY = ("discovery", "idea", "script", "critic", "deliver_script")
PRODUCTION = ("storyboard", "package", "deliver_package")

__all__ = ["DAILY", "PRODUCTION", "STAGES", "StageContext", "StageFn", "run_stage"]
