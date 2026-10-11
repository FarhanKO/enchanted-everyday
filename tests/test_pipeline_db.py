"""The Phase 1 flows end to end, with a scripted model. Needs Postgres.

The daily run goes from discovery to the reviewed script; production adds the storyboard and
package to that script and sends the full package.
"""

from datetime import date

import pytest
from sqlalchemy import select

from engine.db.models import Idea, Run, Script
from engine.db.session import session_scope
from engine.llm.prompts import PROMPT_VERSION
from engine.redo import RedoRefused, prepare_redo
from engine.stages import DAILY, PRODUCTION, STAGES, deliver, idea, run_stage
from engine.stages.idea import OWNER_REJECTED
from tests.fakes import FakeEmbedder, FakeLLM, golden, report

pytestmark = pytest.mark.db
DAY = date(2026, 10, 12)


@pytest.fixture
def sent(monkeypatch):
    messages = []
    monkeypatch.setattr(deliver, "send_message", lambda text, _: messages.append(text))
    monkeypatch.setattr(deliver, "send_document", lambda name, *_: messages.append(name))
    return messages


@pytest.fixture
def embedder(monkeypatch):
    fake = FakeEmbedder(keys=["Premise number 0 "])
    monkeypatch.setattr(idea, "get_embedder", lambda _: fake)
    return fake


def run(names, db_engine, settings, llm) -> dict[str, dict]:
    return {
        name: run_stage(name, STAGES[name], DAY, engine=db_engine, settings=settings, llm=llm)
        for name in names
    }


def _ideas(db_engine) -> dict[int, Idea]:
    with session_scope(db_engine) as s:
        rows = s.scalars(select(Idea).order_by(Idea.id)).all()
        s.expunge_all()
        return {r.id: r for r in rows}


def _scripts(db_engine) -> list[Script]:
    with session_scope(db_engine) as s:
        rows = s.scalars(select(Script).order_by(Script.id)).all()
        s.expunge_all()
        return rows


def test_the_daily_run_ends_with_a_reviewed_script(db_engine, settings, sent, embedder):
    llm = FakeLLM()
    out = run(DAILY, db_engine, settings, llm)

    assert llm.calls == [
        ("story architect", "claude-opus-5-5", "medium"),
        ("script writer", "claude-opus-5-5", "high"),
        ("critic", "claude-opus-5-5", "high"),
    ]
    statuses = sorted(i.status for i in _ideas(db_engine).values())
    assert statuses == ["backup", "backup", "candidate", "candidate", "picked"]
    assert out["idea"]["dedupe"] == "on" and out["idea"]["cards"] == 5

    (row,) = _scripts(db_engine)
    assert row.id == out["critic"]["script_id"] == out["deliver_script"]["script_id"]
    assert row.version == 1 and row.prompt_version == PROMPT_VERSION
    assert row.critic_report["verdict"] == "pass"
    assert row.storyboard is None and row.package is None  # nothing spent on visuals yet

    assert out["deliver_script"]["sent"] is True
    assert sent == [sent[0]] and sent[0].startswith("Today's story")
    with session_scope(db_engine) as s:
        run_row = s.scalars(select(Run)).one()
        assert set(run_row.stages) == set(DAILY)
        assert {v["status"] for v in run_row.stages.values()} == {"done"}
        assert run_row.llm_cost_usd > 0


def test_production_builds_on_the_reviewed_script(db_engine, settings, sent, embedder, fake_media):
    llm = FakeLLM()
    daily = run(DAILY, db_engine, settings, llm)
    out = run(PRODUCTION, db_engine, settings, llm)

    assert llm.roles[-2:] == ["visual director", "packaging"]
    (row,) = _scripts(db_engine)
    assert row.id == daily["critic"]["script_id"] == out["deliver_package"]["script_id"]
    assert row.storyboard and row.package
    assert sent[-1] == f"{out['deliver_package']['episode_id']}.md"


def test_production_needs_a_reviewed_script(db_engine, settings, sent):
    with pytest.raises(RuntimeError, match="'critic' hasn't finished"):
        run(PRODUCTION, db_engine, settings, FakeLLM())


def test_revise_verdict_writes_a_second_version(db_engine, settings, sent, embedder):
    llm = FakeLLM(verdicts=[report("revise", ("script", "high")), report("pass")])
    out = run(DAILY, db_engine, settings, llm)

    assert llm.roles[1:] == ["script writer", "critic", "script writer", "critic"]
    assert out["critic"]["history"] == ["revise", "pass"]
    v1, v2 = _scripts(db_engine)
    assert (v1.version, v2.version) == (1, 2) and v1.idea_id == v2.idea_id
    assert v1.critic_report["verdict"] == "revise" and v2.critic_report["verdict"] == "pass"
    assert out["deliver_script"]["script_id"] == v2.id


def test_reject_verdict_writes_the_first_backup(db_engine, settings, sent, embedder):
    llm = FakeLLM(verdicts=[report("reject", ("story", "high")), report("pass")])
    out = run(DAILY, db_engine, settings, llm)

    ideas = _ideas(db_engine)
    first, backup = out["idea"]["idea_id"], out["idea"]["backups"][0]
    assert ideas[first].status == "rejected" and ideas[backup].status == "picked"
    assert out["critic"]["idea_id"] == backup and out["critic"]["history"] == ["reject", "pass"]
    assert [r.idea_id for r in _scripts(db_engine)] == [first, backup]


def test_a_repeat_of_a_published_story_is_not_picked(db_engine, settings, sent, embedder):
    with session_scope(db_engine) as s:
        earlier = Run(run_date=date(2026, 10, 1), status="complete")
        s.add(earlier)
        s.flush()
        s.add(
            Idea(
                run_id=earlier.id,
                title="An old story",
                premise="p",
                universe="urban",
                card={},
                total_score=30,
                embedding=embedder.embed(["Premise number 0 "])[0],
                status="published",
            )
        )

    out = run(DAILY, db_engine, settings, FakeLLM())

    assert [d["similar_to"] for d in out["idea"]["duplicates"]] == ["An old story"]
    picked = _ideas(db_engine)[out["idea"]["idea_id"]]
    assert "number 0 " not in picked.premise


def test_the_day_survives_a_broken_embedder(db_engine, settings, sent, monkeypatch):
    def broken(_):
        raise OSError("model download failed")

    monkeypatch.setattr(idea, "get_embedder", broken)
    out = run(DAILY, db_engine, settings, FakeLLM())
    assert out["idea"]["dedupe"] == "skipped"
    assert out["deliver_script"]["sent"] is True


# ---------------------------------------------------------------- /redo


def test_redo_writes_the_next_backup_with_the_owners_note(db_engine, settings, sent, embedder):
    llm = FakeLLM()
    first = run(DAILY, db_engine, settings, llm)
    started = prepare_redo(db_engine, DAY, settings, "less sad")
    again = run(DAILY, db_engine, settings, llm)

    assert llm.roles[3:] == ["script writer", "critic"]  # no new story cards to pay for
    assert all("- less sad" in p for p in llm.prompts[3:])
    ideas = _ideas(db_engine)
    old, new = first["idea"]["idea_id"], first["idea"]["backups"][0]
    assert ideas[old].status == OWNER_REJECTED and ideas[new].status == "picked"
    assert started == {
        "resumed": False,
        "rejected_title": ideas[old].title,
        "title": ideas[new].title,
        "redo": 1,
        "backups_left": 1,
    }
    assert again["critic"]["idea_id"] == new
    assert [r.idea_id for r in _scripts(db_engine)] == [old, new]
    assert sent[-1].startswith("Today's story, Mon 12 Oct (redo 1)")
    assert "/redo for another story (1 left)" in sent[-1]


def test_redo_notes_add_up_until_the_backups_run_out(db_engine, settings, sent, embedder):
    llm = FakeLLM()
    run(DAILY, db_engine, settings, llm)
    for note in ("less sad", None):
        prepare_redo(db_engine, DAY, settings, note)
        run(DAILY, db_engine, settings, llm)

    assert "- less sad" in llm.prompts[-1]  # the first redo's note still applies
    assert sent[-1].endswith("No backup stories left for /redo today.")
    with pytest.raises(RedoRefused, match="No backup stories"):
        prepare_redo(db_engine, DAY, settings)
    assert sum(i.status == OWNER_REJECTED for i in _ideas(db_engine).values()) == 2


def test_redo_needs_a_script_and_no_production(db_engine, settings, sent, embedder):
    with pytest.raises(RedoRefused, match="no script"):
        prepare_redo(db_engine, DAY, settings)

    llm = FakeLLM()
    run(DAILY, db_engine, settings, llm)
    run(["storyboard"], db_engine, settings, llm)
    with pytest.raises(RedoRefused, match="settled"):
        prepare_redo(db_engine, DAY, settings)


def test_an_unfinished_redo_is_resumed_not_skipped(db_engine, settings, sent, embedder):
    llm = FakeLLM()
    first = run(DAILY, db_engine, settings, llm)
    prepare_redo(db_engine, DAY, settings)
    run(["script"], db_engine, settings, llm)  # stopped before the critic

    resumed = prepare_redo(db_engine, DAY, settings)
    out = run(DAILY, db_engine, settings, llm)

    assert resumed["resumed"] is True and resumed["redo"] == 1
    assert out["critic"]["idea_id"] == first["idea"]["backups"][0]
    assert sum(i.status == OWNER_REJECTED for i in _ideas(db_engine).values()) == 1
    assert out["deliver_script"]["sent"] is True


def test_a_turned_down_story_is_never_offered_again(db_engine, settings, sent, embedder, tmp_path):
    first = run(DAILY, db_engine, settings, FakeLLM())
    prepare_redo(db_engine, DAY, settings)
    rejected = _ideas(db_engine)[first["idea"]["idea_id"]]
    assert rejected.slate_id

    stories = [(rejected.slate_id, rejected.universe), ("zz-other", rejected.universe)]
    (tmp_path / "slate.toml").write_text(
        "".join(
            f'[[story]]\nid = "{sid}"\ntitle = "t"\npremise = "p"\nuniverse = "{u}"\n\n'
            for sid, u in stories
        ),
        encoding="utf-8",
    )
    later = settings.model_copy(update={"brand_dir": str(tmp_path)})
    out = run_stage(
        "discovery", STAGES["discovery"], date(2026, 10, 13), engine=db_engine, settings=later
    )
    assert out["candidates"] == ["zz-other"]


# ---------------------------------------------------------------- connected episodes


def test_the_next_episode_reads_the_story_so_far(db_engine, settings, sent, embedder, fake_media):
    llm = FakeLLM()
    run(DAILY, db_engine, settings, llm)
    run(PRODUCTION, db_engine, settings, llm)  # produced, so its canon note is now the story so far
    for name in DAILY:
        run_stage(
            name, STAGES[name], date(2026, 10, 13), engine=db_engine, settings=settings, llm=llm
        )

    prompts = dict.fromkeys(("story architect", "script writer", "critic"), "")
    for (role, _, _), prompt in zip(llm.calls, llm.prompts, strict=True):
        if role in prompts:
            prompts[role] = prompt  # the latest call of each role: day two
    summary = golden()["package"]["canon"]["summary"]
    for role, prompt in prompts.items():
        assert "<story_so_far>" in prompt and summary[:40] in prompt, role
    assert "Last 1 picks: modes narrated 1, mixed 0, dialogue 0" in prompts["story architect"]
    assert "lost-dreams thread last moved 0 pick(s) ago" in prompts["story architect"]

    # day one told the season plan's first step; the thread rests on day two
    first_architect = llm.prompts[llm.roles.index("story architect")]
    assert 'Next step: D1 "Three falling notes"' in first_architect
    assert 'Told so far: D1 "Three falling notes"' in prompts["story architect"]
    assert "The thread moved in the latest pick" in prompts["story architect"]
    # the pilot's open questions are listed with ids every later episode can close
    question = golden()["package"]["canon"]["open_threads"][0]
    for role, prompt in prompts.items():
        assert "<open_threads>" in prompt and question in prompt, role
