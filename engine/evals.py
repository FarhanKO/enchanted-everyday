"""The golden-set eval: does a prompt change make scripts better or worse?

Every episode in stories/*/episode.json is one the owner approved. For each, the script writer
writes a fresh script from the episode's story card and the critic reviews it. The results are saved
to evals/results/, and compared with the previous file. A lower pass rate blocks a prompt change.

This spends real money (two or more calls per golden episode), so it never runs in CI.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from engine.budget import BudgetExceeded
from engine.config import Settings
from engine.llm.client import LLMError, LLMProvider, parse_as
from engine.llm.prompts import PROMPT_VERSION
from engine.llm.schemas import Episode
from engine.studio import Studio

log = logging.getLogger(__name__)


class MeteredCall:
    """A studio `call` without the database: routes like the pipeline, stops at a spend cap."""

    def __init__(self, llm: LLMProvider, settings: Settings, cap_usd: Decimal) -> None:
        self.llm, self.settings, self.cap, self.spent = llm, settings, cap_usd, Decimal(0)

    def __call__[M: BaseModel](
        self, *, system: str, user: str, schema: dict[str, Any], model: type[M], role: str
    ) -> M:
        if self.spent >= self.cap:
            raise BudgetExceeded(f"eval spent ${self.spent:.2f} of its ${self.cap:.2f} cap")
        llm_model, effort = self.settings.llm_for(role)
        result = self.llm.complete_json(
            system=system, user=user, schema=schema, model=llm_model, effort=effort
        )
        self.spent += result.cost_usd
        return parse_as(result, model)


@dataclass
class Case:
    episode: str
    valid: bool
    verdict: str | None = None
    high_issues: int = 0
    low_issues: int = 0
    words: int | None = None
    seconds: float | None = None
    repairs: int = 0
    error: str | None = None


def golden_paths(stories_dir: Path) -> list[Path]:
    return sorted(stories_dir.glob("*/episode.json"))


def run_case(studio: Studio, path: Path) -> Case:
    ep = Episode.model_validate_json(path.read_text(encoding="utf-8"))
    before = studio.repairs
    try:
        script = studio.script(ep.card)
        report = studio.review(ep.card, script)
    except LLMError as e:
        return Case(ep.id, valid=False, repairs=studio.repairs - before, error=str(e)[:300])
    high = sum(i.severity == "high" for i in report.issues)
    return Case(
        ep.id,
        valid=True,
        verdict=report.verdict,
        high_issues=high,
        low_issues=len(report.issues) - high,
        words=script.word_count,
        seconds=round(script.estimated_duration_s, 1),
        repairs=studio.repairs - before,
    )


def pass_rate(cases: list[dict[str, Any]]) -> float:
    return sum(c["verdict"] == "pass" for c in cases) / len(cases) if cases else 0.0


def run_evals(studio: Studio, paths: list[Path], results_dir: Path) -> dict[str, Any]:
    cases = [asdict(run_case(studio, p)) for p in paths]
    previous = sorted(results_dir.glob("*.json"))
    report = {
        "prompt_version": PROMPT_VERSION,
        "ran_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "pass_rate": round(pass_rate(cases), 3),
        "cases": cases,
    }
    if previous:
        last = json.loads(previous[-1].read_text(encoding="utf-8"))
        report["previous"] = {
            "file": previous[-1].name,
            "prompt_version": last["prompt_version"],
            "pass_rate": last["pass_rate"],
        }
    results_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    out = results_dir / f"{stamp}-{PROMPT_VERSION}.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    report["file"] = str(out)
    return report
