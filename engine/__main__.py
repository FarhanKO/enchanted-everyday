"""CLI: `python -m engine <command>` (or `engine <command>` once installed).

migrate   apply database migrations
check     report missing settings and test the database connection
run       run the daily flow once (optionally for --date YYYY-MM-DD)
serve     start the scheduled deployment (what the worker container runs)
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
    "phase 1 (trends, scripts)": [
        "niche",
        "anthropic_api_key",
        "telegram_bot_token",
        "telegram_owner_id",
    ],
    "phase 2 (video)": [
        "r2_account_id",
        "r2_access_key_id",
        "r2_secret_access_key",
        "pexels_api_key",
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="engine")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate")
    sub.add_parser("check")
    run_p = sub.add_parser("run")
    run_p.add_argument("--date", help="run date YYYY-MM-DD (default: today in TIMEZONE)")
    sub.add_parser("serve")
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
