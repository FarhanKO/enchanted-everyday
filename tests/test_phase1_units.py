"""Phase 1 parts that need no database: picking, messages, routing, token hygiene, evals."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import get_args

import httpx
import pytest

from engine import notify
from engine.config import AGENT_ROLES, Settings
from engine.evals import MeteredCall, golden_paths, run_evals
from engine.llm.prompts import ROLES
from engine.llm.schemas import (
    CriticReport,
    Episode,
    Script,
    Speaker,
    StoryCard,
    check_speakers,
)
from engine.notify import TEXT_LIMIT, TelegramError
from engine.stages.deliver import script_message
from engine.stages.idea import BACKUPS, DUPLICATE_SIMILARITY, Scored, assign
from engine.studio import Studio
from tests.conftest import ROOT
from tests.fakes import FakeCall, FakeLLM, golden, report


def _scored(ref: str, total: float, similarity: float | None = None) -> Scored:
    card = golden()["card"]
    card["scores"] = {
        "hook": total / 4,
        "emotion": total / 4,
        "visual": total / 4,
        "brand_fit": total / 4,
    }
    return Scored(ref, ref, StoryCard.model_validate(card), similarity=similarity)


def test_assign_picks_the_best_fresh_card_and_keeps_backups():
    scored = assign(
        [
            _scored("a", 24),
            _scored("b", 36, similarity=DUPLICATE_SIMILARITY + 0.01),  # best, but a repeat
            _scored("c", 32),
            _scored("d", 28, similarity=DUPLICATE_SIMILARITY - 0.01),  # close, not a repeat
            _scored("e", 20),
        ]
    )
    status = {s.ref: s.status for s in scored}
    assert status == {
        "a": "backup",
        "b": "duplicate",
        "c": "picked",
        "d": "backup",
        "e": "candidate",
    }
    assert sum(v == "backup" for v in status.values()) == BACKUPS


def test_assign_with_only_duplicates_picks_nothing():
    scored = assign([_scored("a", 30, similarity=0.99)])
    assert [s.status for s in scored] == ["duplicate"]


def test_script_message_is_ready_to_record():
    ep = Episode.model_validate(golden())
    critique = CriticReport.model_validate(report("revise", ("script", "high"), ("story", "low")))
    text = script_message(ep.card, ep.script, critique, date(2026, 10, 12))
    assert text.startswith("Today's story, Mon 12 Oct")
    for line in ep.script.lines:
        assert f"{line.text}  ({line.delivery})" in text  # every line, with its delivery note
    assert "[pause 1.5s]" in text
    assert "Critic: revise (1 high, 1 low)" in text
    assert "- script: script problem" in text
    assert "story problem" not in text  # low issues are listed only when there are no high ones
    assert "/produce to build the storyboard and production package." in text
    assert text.endswith("No backup stories left for /redo today.")
    assert len(text) < TEXT_LIMIT


def test_script_message_after_a_redo():
    ep = Episode.model_validate(golden())
    critique = CriticReport.model_validate(report("pass"))
    text = script_message(ep.card, ep.script, critique, date(2026, 10, 12), redo=1, backups_left=1)
    assert text.startswith("Today's story, Mon 12 Oct (redo 1)")
    assert text.endswith("Or /redo for another story (1 left), with a note if you like.")


def test_each_agent_gets_its_own_model_and_effort():
    s = Settings(_env_file=None, llm_models={"packager": "claude-sonnet-5-5"})
    assert s.llm_for("packager") == ("claude-sonnet-5-5", "medium")
    assert s.llm_for("script_writer") == ("claude-opus-5-5", "high")  # default effort override
    assert s.llm_for("critic") == ("claude-opus-5-5", "high")
    assert s.llm_for("visual_director") == ("claude-opus-5-5", "medium")
    assert s.llm_for(None) == ("claude-opus-5-5", "medium")


@pytest.mark.parametrize(
    "bad",
    [
        {"llm_models": {"scriptwriter": "claude-sonnet-5-5"}},  # typo in a role name
        {"llm_efforts": {"critic": "extreme"}},
        {"llm_effort": "hi"},
    ],
)
def test_bad_agent_settings_fail_at_startup(bad):
    with pytest.raises(ValueError):
        Settings(_env_file=None, **bad)


def test_agent_roles_match_the_role_prompts():
    assert set(AGENT_ROLES) == set(ROLES)


def test_eval_calls_route_like_the_pipeline():
    llm = FakeLLM()
    call = MeteredCall(llm, Settings(_env_file=None), Decimal(1))
    Studio(call, ROOT / "brand").script(StoryCard.model_validate(golden()["card"]))
    assert llm.calls == [("script writer", "claude-opus-5-5", "high")]
    assert call.spent == Decimal("0.01")


def test_telegram_errors_never_contain_the_token(monkeypatch):
    settings = Settings(_env_file=None, telegram_bot_token="123:SECRET-TOKEN", telegram_owner_id=42)

    def boom(url, **_):
        raise httpx.ConnectError(f"cannot reach {url}")

    monkeypatch.setattr(notify.httpx, "post", boom)
    with pytest.raises(TelegramError) as e:
        notify.send_message("hi", settings)
    assert "SECRET" not in str(e.value) and e.value.__cause__ is None
    assert notify.alert("hi", settings) is False  # alert swallows it


def test_eval_writes_results_and_compares_with_the_last(tmp_path):
    ep = golden()
    paths = golden_paths(ROOT / "stories")
    assert paths, "the golden set is empty"

    first = run_evals(
        Studio(FakeCall(*[ep["script"], report("pass")] * len(paths)), ROOT / "brand"),
        paths,
        tmp_path,
    )
    assert first["pass_rate"] == 1.0 and "previous" not in first

    second = run_evals(
        Studio(FakeCall(*[ep["script"], report("revise")] * len(paths)), ROOT / "brand"),
        paths,
        tmp_path,
    )
    assert second["pass_rate"] == 0.0
    assert second["previous"]["pass_rate"] == 1.0
    saved = json.loads(Path(second["file"]).read_text(encoding="utf-8"))
    assert saved["cases"][0]["verdict"] == "revise"


def test_voice_cast_uses_only_built_in_voices():
    import tomllib

    allowed = {
        "adam", "alice", "bella", "bill", "brian", "callum", "charlie", "chris", "daniel", "eric",
        "george", "harry", "jessica", "laura", "liam", "lily", "matilda", "river", "roger", "sarah",
        "will",
    }  # fmt: skip
    cast = tomllib.loads((ROOT / "brand" / "voices.toml").read_text(encoding="utf-8"))
    roles = {k: v for k, v in cast.items() if isinstance(v, dict)}
    assert {"narrator", "fann", "tina", "shopkeeper", "child_girl"} <= set(roles)
    for role, spec in roles.items():
        assert spec["voice"] in allowed, role
        assert spec.get("backup", spec["voice"]) in allowed, role
        assert spec["sample"].strip(), role
    # the leads never share a voice with the narrator or each other
    leads = [roles[r]["voice"] for r in ("narrator", "fann", "tina", "shopkeeper")]
    assert len(set(leads)) == len(leads)


def _script_with(*speakers: str) -> Script:
    data = golden()["script"]
    lines = [line for beat in data["beats"] for line in beat["lines"]]
    for line, who in zip(lines, speakers, strict=False):
        line["speaker"] = who
    return Script.model_validate(data)


@pytest.mark.parametrize(
    ("mode", "speakers", "error"),
    [
        ("narrated", (), None),
        ("narrated", ("narrator", "tina"), "only the narrator"),
        ("dialogue", ("fann", "shopkeeper") * 9, None),
        ("dialogue", ("fann",), "narrator has no lines"),
        ("mixed", ("narrator", "tina"), None),
        ("mixed", (), "both the narrator and at least one character"),
        ("mixed", ("fann", "tina", "shopkeeper", "woman"), "max 3"),
    ],
)
def test_the_mode_decides_who_speaks(mode, speakers, error):
    script = _script_with(*speakers)
    if error is None:
        check_speakers(mode, script)
    else:
        with pytest.raises(ValueError, match=error):
            check_speakers(mode, script)


def test_voice_cast_covers_every_speaker():
    import tomllib

    cast = tomllib.loads((ROOT / "brand" / "voices.toml").read_text(encoding="utf-8"))
    roles = {k for k, v in cast.items() if isinstance(v, dict)}
    assert roles == set(get_args(Speaker))


def test_signature_and_character_sounds_are_defined():
    import tomllib

    sound = tomllib.loads((ROOT / "brand" / "sound.toml").read_text(encoding="utf-8"))
    assert sound["signature"]["line"] == "Goodnight, sleepless soul."
    assert set(sound["characters"]) == {"fann", "tina", "shopkeeper"}
    assert sound["signature"]["bell"] == sound["characters"]["shopkeeper"]["presence"]


def test_script_message_names_character_speakers():
    ep = Episode.model_validate(golden())
    script = _script_with("tina", "child_girl")
    text = script_message(
        ep.card, script, CriticReport.model_validate(report()), date(2026, 10, 12)
    )
    assert f"TINA: {script.lines[0].text}" in text
    assert f"CHILD GIRL: {script.lines[1].text}" in text
    assert f"\n{script.lines[2].text}  (" in text  # the narrator needs no label
    assert "emotional · fable · narrated" in text
