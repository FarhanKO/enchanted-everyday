"""CLI: `python -m engine <command>` (or `engine <command>` once installed).

migrate   apply database migrations
check     report missing settings and test the database connection
run       run the daily flow once (optionally for --date YYYY-MM-DD)
produce   write the storyboard and package for a day's script (optionally --date)
redo      turn down a day's story and write the next backup (optionally --date, --note)
serve     start the scheduled deployments (what the worker container runs)
tokens    check the Meta and YouTube logins; send fix-it steps to Telegram (--quiet: print only)
render    voice, draw and render an episode.json to video, no database (spends up to --max-usd)
episode   validate an episode.json and write its human-readable episode.md
schemas   export the agent contracts as JSON Schema files to schemas/
eval      rewrite and review every golden episode's script; compare with the last eval (costs money)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from engine.config import get_settings
from engine.log import setup_logging

# settings each phase needs; `check` reports the gaps
REQUIRED = {
    "core": ["database_url"],
    "phase 1 (stories, scripts)": [
        "llm_api_key",  # OPENROUTER_API_KEY or ANTHROPIC_API_KEY
        "telegram_bot_token",
        "telegram_owner_id",
    ],
    "phase 2 (video)": ["openrouter_api_key"],  # images and voice go through OpenRouter
    "phase 3 (publishing)": [
        "r2_account_id",
        "r2_access_key_id",
        "r2_secret_access_key",
        "r2_public_base_url",
    ],
    "monitoring": ["healthcheck_ping_url"],
}


def migrate() -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).parent / "db" / "migrations"))
    command.upgrade(cfg, "head")


def check() -> int:
    from sqlalchemy import text

    from engine.db.session import get_engine

    settings = get_settings()
    for group, names in REQUIRED.items():
        missing = [n for n in names if not getattr(settings, n)]
        print(
            f"{'ok ' if not missing else '-- '} {group}"
            + (f": missing {missing}" if missing else "")
        )
    try:
        with get_engine().connect() as conn:
            conn.execute(text("select 1"))
        print("ok  database reachable")
        return 0
    except Exception as e:
        print(f"!! database unreachable: {e}")
        return 1


def run(run_date: str | None) -> None:
    from engine.flows import daily_run

    daily_run(run_date=run_date)


def produce(run_date: str | None) -> None:
    from engine.flows import produce as produce_flow

    produce_flow(run_date=run_date)


def redo(run_date: str | None, note: str | None) -> int:
    from datetime import date

    from engine.db.session import get_engine
    from engine.flows import daily_run, today
    from engine.redo import RedoRefused, prepare_redo

    settings = get_settings()
    day = date.fromisoformat(run_date) if run_date else today(settings)
    try:
        started = prepare_redo(get_engine(), day, settings, note)
    except RedoRefused as e:
        print(f"-- {e}")
        return 1
    print(f"ok  writing '{started['title']}' (redo {started['redo']})")
    daily_run(run_date=str(day))
    return 0


def serve() -> None:
    from prefect import serve as serve_all
    from prefect.schedules import Cron

    from engine.flows import daily_run, token_check

    settings = get_settings()
    serve_all(
        daily_run.to_deployment(
            name="daily",
            schedules=[Cron(settings.daily_run_cron, timezone=settings.timezone)],
        ),
        token_check.to_deployment(
            name="tokens",
            schedules=[Cron(settings.login_check_cron, timezone=settings.timezone)],
        ),
    )


def tokens(quiet: bool) -> int:
    from engine.notify import alert
    from engine.tokens import check_tokens

    messages = check_tokens()
    if not messages:
        print("ok  Meta and YouTube logins are healthy (or not configured)")
        return 0
    for message in messages:
        print(f"-- {message}\n")
        if not quiet:
            alert(message)
    return 1


def _recent_music(out_dir: Path) -> list[str]:
    """Without a database: the tracks in the other local renders, newest first."""
    import json

    others = [
        p for p in out_dir.parent.glob("*/music.json") if p.parent.resolve() != out_dir.resolve()
    ]
    heard: list[str] = []
    for p in sorted(others, key=lambda p: p.stat().st_mtime, reverse=True):
        heard += [m["file"] for m in json.loads(p.read_text(encoding="utf-8")) if m.get("file")]
    return heard


def render_file(path: str, out: str | None, max_usd: float, only: str | None) -> int:
    import json
    from decimal import Decimal

    from engine.llm.schemas import Episode
    from engine.media.episode import makers, produce_episode
    from engine.media.paid import CapLedger

    settings = get_settings()
    src = Path(path)
    ep = Episode.model_validate(json.loads(src.read_text(encoding="utf-8")))
    ledger = CapLedger(Decimal(str(max_usd)))
    m = makers(settings, ledger)
    out_dir = Path(out) if out else Path(settings.work_dir) / "renders" / src.parent.name
    try:
        if only:  # one frame, to check the look before paying for the rest
            shot = next(s for s in ep.storyboard.shots if s.id == only)
            board = ep.storyboard.model_copy(update={"shots": [shot]})
            frames = m.frames.make(board)
            print(f"ok  {only}: {frames.shots[only]}")
            return 0
        voice, frames, result = produce_episode(
            ep, out_dir, settings, m, recent_music=_recent_music(out_dir)
        )
        (out_dir / "music.json").write_text(json.dumps(result.qc["music"], indent=2), "utf-8")
    finally:
        (out_dir / "ledger.json").parent.mkdir(parents=True, exist_ok=True)
        (out_dir / "ledger.json").write_text(json.dumps(ledger.entries, indent=2), "utf-8")
        print(f"spent ${ledger.spent_usd:.3f} of ${max_usd:.2f}")
    qc = result.qc
    mark = "ok " if qc["passed"] else "-- "
    print(f"{mark} {result.path} ({qc['duration_s']}s, {qc['size_mb']} MB)")
    for line in qc["issues"] + qc["notes"]:
        print(f"    {line}")
    for m in qc["music"]:
        print(f"    music {m['from_s']:.0f}-{m['to_s']:.0f}s {m['mood']}: {m['title']}")
    return 0 if qc["passed"] else 1


def episode(path: str) -> int:
    import json

    from pydantic import ValidationError

    from engine.episode_doc import to_markdown
    from engine.llm.schemas import Episode

    src = Path(path)
    try:
        ep = Episode.model_validate(json.loads(src.read_text(encoding="utf-8")))
    except ValidationError as e:
        print(f"!! {src} is not a valid episode:\n{e}")
        return 1
    dest = src.with_suffix(".md")
    dest.write_text(to_markdown(ep), encoding="utf-8")
    print(f"ok  {ep.script.word_count} words, ~{ep.script.estimated_duration_s:.0f}s -> {dest}")
    return 0


def schemas(out_dir: str = "schemas") -> None:
    import json

    from engine.llm import schemas as s

    out = Path(out_dir)
    out.mkdir(exist_ok=True)
    for model in (s.StoryCards, s.Script, s.Storyboard, s.Package, s.CriticReport, s.Episode):
        path = out / f"{model.__name__}.schema.json"
        path.write_text(json.dumps(model.model_json_schema(), indent=2) + "\n", encoding="utf-8")
        print(f"ok  {path}")


def evaluate(max_usd: float) -> int:
    from decimal import Decimal

    from engine.evals import MeteredCall, golden_paths, run_evals
    from engine.flows import build_llm
    from engine.studio import Studio

    settings = get_settings()
    llm = build_llm(settings)
    if llm is None:
        print("!! neither OPENROUTER_API_KEY nor ANTHROPIC_API_KEY is set")
        return 1
    paths = golden_paths(Path("stories"))
    if not paths:
        print("!! no golden episodes in stories/*/episode.json")
        return 1
    call = MeteredCall(llm, settings, Decimal(str(max_usd)))
    report = run_evals(Studio(call, Path(settings.brand_dir)), paths, Path("evals/results"))
    for c in report["cases"]:
        detail = c["error"] or (
            f"{c['verdict']}, {c['high_issues']} high / {c['low_issues']} low, "
            f"{c['words']} words, {c['seconds']}s, {c['repairs']} repairs"
        )
        print(f"{'ok ' if c['verdict'] == 'pass' else '-- '} {c['episode']}: {detail}")
    print(f"pass rate {report['pass_rate']:.0%} with prompts {report['prompt_version']}")
    if prev := report.get("previous"):
        print(f"previous  {prev['pass_rate']:.0%} with prompts {prev['prompt_version']}")
    print(f"spent ${call.spent:.2f} -> {report['file']}")
    worse = prev is not None and report["pass_rate"] < prev["pass_rate"]
    return 1 if worse else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="engine")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate")
    sub.add_parser("check")
    run_p = sub.add_parser("run")
    run_p.add_argument("--date", help="run date YYYY-MM-DD (default: today in TIMEZONE)")
    prod_p = sub.add_parser("produce")
    prod_p.add_argument("--date", help="run date YYYY-MM-DD (default: today in TIMEZONE)")
    redo_p = sub.add_parser("redo")
    redo_p.add_argument("--date", help="run date YYYY-MM-DD (default: today in TIMEZONE)")
    redo_p.add_argument("--note", help="what to do differently, for the writer and critic")
    sub.add_parser("serve")
    tok_p = sub.add_parser("tokens")
    tok_p.add_argument("--quiet", action="store_true", help="print only; send nothing")
    ren_p = sub.add_parser("render")
    ren_p.add_argument("path", help="path to an episode.json")
    ren_p.add_argument("--out", help="output folder (default: WORK_DIR/renders/<episode folder>)")
    ren_p.add_argument("--max-usd", type=float, default=1.0, help="stop spending past this")
    ren_p.add_argument("--only", help="draw just this shot (e.g. S01) to check the look")
    ep_p = sub.add_parser("episode")
    ep_p.add_argument("path", help="path to an episode.json")
    sub.add_parser("schemas")
    eval_p = sub.add_parser("eval")
    eval_p.add_argument("--max-usd", type=float, default=3.0, help="stop spending past this")
    args = parser.parse_args(argv)

    setup_logging(get_settings().log_level)
    if args.cmd == "migrate":
        migrate()
    elif args.cmd == "check":
        return check()
    elif args.cmd == "run":
        run(args.date)
    elif args.cmd == "produce":
        produce(args.date)
    elif args.cmd == "redo":
        return redo(args.date, args.note)
    elif args.cmd == "serve":
        serve()
    elif args.cmd == "tokens":
        return tokens(args.quiet)
    elif args.cmd == "render":
        return render_file(args.path, args.out, args.max_usd, args.only)
    elif args.cmd == "episode":
        return episode(args.path)
    elif args.cmd == "schemas":
        schemas()
    elif args.cmd == "eval":
        return evaluate(args.max_usd)
    return 0


if __name__ == "__main__":
    sys.exit(main())
