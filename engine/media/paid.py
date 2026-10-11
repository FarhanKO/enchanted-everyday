"""Paying for media, once.

Every paid call goes through a cache keyed on everything that shapes the result (model, voice,
prompt, reference files), so a retried stage or a re-render reuses what was already bought. Before
paying, `Ledger.check` enforces the daily cap; after, `Ledger.record` books the cost at once,
outside the stage's transaction, so a stage that later fails still counts what it spent.
"""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Protocol


class Ledger(Protocol):
    def check(self, estimate_usd: Decimal) -> None:
        """Raise (BudgetExceeded) if paying `estimate_usd` more would pass the cap."""

    def record(
        self, kind: str, provider: str, cost_usd: Decimal, path: Path, meta: dict
    ) -> None: ...


@dataclass
class CapLedger:
    """A ledger with no database: a fixed allowance, for `engine render` on a local episode."""

    cap_usd: Decimal
    spent_usd: Decimal = Decimal(0)
    entries: list[dict] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def check(self, estimate_usd: Decimal) -> None:
        from engine.budget import BudgetExceeded

        if self.spent_usd + estimate_usd > self.cap_usd:
            raise BudgetExceeded(
                f"${self.spent_usd + estimate_usd:.3f} would pass the ${self.cap_usd:.2f} allowance"
            )

    def record(self, kind: str, provider: str, cost_usd: Decimal, path: Path, meta: dict) -> None:
        with self._lock:  # frames are drawn a few at a time
            self.spent_usd += cost_usd
            self.entries.append(
                {"kind": kind, "provider": provider, "cost_usd": str(cost_usd), "path": str(path)}
                | meta
            )


def cache_key(*parts: str | bytes | Path) -> str:
    h = hashlib.sha256()
    for part in parts:
        if isinstance(part, Path):
            h.update(hashlib.sha256(part.read_bytes()).digest())
        elif isinstance(part, str):
            h.update(part.encode("utf-8"))
        else:
            h.update(part)
        h.update(b"\x00")
    return h.hexdigest()[:24]
