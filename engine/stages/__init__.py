"""Pipeline stages and the order the flows run them in.

The daily run writes and reviews the story; production only starts once the owner has the script,
so a script they'd reject never costs a storyboard. Every stage of a day shares that day's run row,
so production stages read the story stages' outputs.

Production (/produce) writes the storyboard and package, sends the package, then voices,
draws and renders the video and sends it for approval (Approve / Skip in the bot; /reshoot to
redraw a frame). Coming next, by phase:
  Phase 3: publish
  Phase 4: analytics (separate scheduled flow)
"""

from engine.stages import deliver, discovery, idea, media, story
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
    "voice": media.voice,
    "images": media.images,
    "render": media.render,
    "deliver_render": media.deliver_render,
}

DAILY = ("discovery", "idea", "script", "critic", "deliver_script")
PRODUCTION = (
    "storyboard",
    "package",
    "deliver_package",
    "voice",
    "images",
    "render",
    "deliver_render",
)
# what a /reshoot redoes: the frames (only the asked-for ones are bought again), render, delivery
RESHOOT = ("images", "render", "deliver_render")

__all__ = ["DAILY", "PRODUCTION", "RESHOOT", "STAGES", "StageContext", "StageFn", "run_stage"]
