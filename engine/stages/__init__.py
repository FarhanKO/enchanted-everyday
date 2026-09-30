"""Pipeline stages, in the order the daily flow runs them.

Built so far: trend. Coming next, by phase:
  Phase 1: idea (score + pgvector dedupe), script (JSON + critic pass)
  Phase 2: assets, render, approve
  Phase 3: publish
  Phase 4: analytics (separate scheduled flow)
"""

from engine.stages import trend
from engine.stages.base import StageContext, StageFn, run_stage

PIPELINE: dict[str, StageFn] = {
    "trend": trend.run,
}

__all__ = ["PIPELINE", "StageContext", "StageFn", "run_stage"]
