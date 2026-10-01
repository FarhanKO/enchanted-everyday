"""Pipeline stages, in the order the daily flow runs them.

Built so far: discovery. Coming next, by phase:
  Phase 1: idea (story cards + pgvector dedupe), script, storyboard, package, critic
  Phase 2: assets, render, approve
  Phase 3: publish
  Phase 4: analytics (separate scheduled flow)
"""

from engine.stages import discovery
from engine.stages.base import StageContext, StageFn, run_stage

PIPELINE: dict[str, StageFn] = {
    "discovery": discovery.run,
}

__all__ = ["PIPELINE", "StageContext", "StageFn", "run_stage"]
