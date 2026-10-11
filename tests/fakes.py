"""Stand-ins for the model and the embedder: scripted answers, no network, no spend."""

from __future__ import annotations

import copy
import json
import re
from collections import deque
from decimal import Decimal
from typing import Any

from engine.llm.client import LLMResult, parse_as
from tests.conftest import GOLDEN_EPISODE


def golden() -> dict[str, Any]:
    return json.loads(GOLDEN_EPISODE.read_text(encoding="utf-8"))


def report(verdict: str = "pass", *issues: tuple[str, str]) -> dict[str, Any]:
    """A critic report; issues are (area, severity) pairs."""
    return {
        "verdict": verdict,
        "issues": [
            {
                "area": area,
                "rule": 0,
                "problem": f"{area} problem",
                "fix": f"{area} fix",
                "severity": severity,
            }
            for area, severity in issues
        ],
    }


class FakeCall:
    """A studio `call` that answers from a queue, validating like the real one."""

    def __init__(self, *answers: dict[str, Any]) -> None:
        self.answers = deque(answers)
        self.prompts: list[dict[str, str]] = []

    def __call__(self, *, system, user, schema, model, role):
        self.prompts.append({"system": system, "user": user, "role": role})
        data = self.answers.popleft()
        return parse_as(LLMResult(data, "fake", 0, 0, Decimal(0)), model)


ROLE = re.compile(r"^# Role: (.+)$", re.MULTILINE)


class FakeLLM:
    """An LLMProvider for whole-pipeline tests: answers each role with the golden episode.

    `verdicts` is the critic's answers in order; `scores` maps a ref to score overrides.
    `calls` records (role, model, effort) for every call, `prompts` its user message.
    """

    def __init__(self, verdicts: list[dict[str, Any]] | None = None, scores=None) -> None:
        self.ep = golden()
        self.verdicts = deque(verdicts or [report("pass")])
        self.scores = scores or {}
        self.calls: list[tuple[str, str | None, str | None]] = []
        self.prompts: list[str] = []  # the user message of every call

    @property
    def roles(self) -> list[str]:
        return [role for role, _, _ in self.calls]

    def _cards(self, user: str) -> dict[str, Any]:
        refs = re.findall(r"^- ref (\S+) ", user, re.MULTILINE)
        new = re.search(r"Also write (\d+) new", user)
        refs += ["new"] * (int(new.group(1)) if new else 0)
        step = re.search(r"^Next step: (D\d+)", user, re.MULTILINE)  # obeys the season plan
        cards = []
        for n, ref in enumerate(refs):
            card = copy.deepcopy(self.ep["card"])
            card["title"] = f"Story {ref} {n}"
            card["premise"] = f"Premise number {n} about {ref}, entirely different from the rest."
            card["scores"] = {"hook": 5, "emotion": 5, "visual": 5, "brand_fit": 5}
            card["scores"].update(self.scores.get(ref, {}))
            card["advances_dreams_thread"] = bool(step)
            card["dreams_step"] = step.group(1) if step else ""
            cards.append({"ref": ref, "card": card})
        return {"cards": cards}

    def complete_json(self, *, system, user, schema, max_tokens=16000, model=None, effort=None):
        role = ROLE.search(system).group(1)
        self.calls.append((role, model, effort))
        self.prompts.append(user)
        data = {
            "story architect": lambda: self._cards(user),
            "script writer": lambda: self.ep["script"],
            "visual director": lambda: self.ep["storyboard"],
            "packaging": lambda: self.ep["package"],
            "critic": lambda: self.verdicts.popleft() if self.verdicts else report("pass"),
        }[role]()
        return LLMResult(copy.deepcopy(data), "fake", 0, 0, Decimal("0.01"))


class FakeEmbedder:
    """Texts containing the same key get the same vector; every other text gets its own."""

    def __init__(self, keys: list[str] = ()) -> None:
        self.keys = list(keys)
        self.others: dict[str, int] = {}

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            axis = next((i for i, k in enumerate(self.keys) if k in text), None)
            if axis is None:
                axis = self.others.setdefault(text, 383 - len(self.others))
            v = [0.0] * 384
            v[axis] = 1.0
            out.append(v)
        return out
