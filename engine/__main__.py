"""CLI: `python -m engine <command>` (or `engine <command>` once installed).

migrate   apply database migrations
check     report missing settings and test the database connection
run       run the daily flow once (optionally for --date YYYY-MM-DD)
serve     start the scheduled deployment (what the worker container runs)
episode   validate an episode.json and write its human-readable episode.md
schemas   export the agent contracts as JSON Schema files to schemas/
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
        "anthropic_api_key",
        "telegram_bot_token",
        "telegram_owner_id",
    ],
    "phase 2 (video)": [
        "r2_account_id",
        "r2_access_key_id",
        "r2_secret_access_key",
    ],
    "phase 3 (publishing)": ["r2_public_base_url"],
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


def serve() -> None:
    from prefect.schedules import Cron

    from engine.flows import daily_run

    settings = get_settings()
    daily_run.serve(
        name="daily",
        schedules=[Cron(settings.daily_run_cron, timezone=settings.timezone)],
    )


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="engine")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate")
    sub.add_parser("check")
    run_p = sub.add_parser("run")
    run_p.add_argument("--date", help="run date YYYY-MM-DD (default: today in TIMEZONE)")
    sub.add_parser("serve")
    ep_p = sub.add_parser("episode")
    ep_p.add_argument("path", help="path to an episode.json")
    sub.add_parser("schemas")
    args = parser.parse_args(argv)

    setup_logging(get_settings().log_level)
    if args.cmd == "migrate":
        migrate()
    elif args.cmd == "check":
        return check()
    elif args.cmd == "run":
        run(args.date)
    elif args.cmd == "serve":
        serve()
    elif args.cmd == "episode":
        return episode(args.path)
    elif args.cmd == "schemas":
        schemas()
    return 0


if __name__ == "__main__":
    sys.exit(main())
