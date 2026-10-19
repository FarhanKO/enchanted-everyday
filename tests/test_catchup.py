"""The catch-up check `engine serve` makes at start, for a machine that was off at run time.
Needs Postgres."""

from datetime import date, datetime

import pytest

from engine.db.models import Run
from engine.db.session import session_scope
from engine.flows import missed_daily_run

pytestmark = pytest.mark.db
TUESDAY = date(2026, 10, 20)  # a run day under "0 5 * * 0,2,4,6"


def at(settings, day: date, hh: int, mm: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hh, mm, tzinfo=settings.tz)


@pytest.fixture
def four_a_week(settings):
    settings.daily_run_cron = "0 5 * * 0,2,4,6"
    return settings


def add_run(db_engine, status: str) -> None:
    with session_scope(db_engine) as s:
        s.add(Run(run_date=TUESDAY, status=status))


def test_a_run_day_never_started_is_caught_up(db_engine, four_a_week):
    assert missed_daily_run(four_a_week, at(four_a_week, TUESDAY, 9), db_engine) == TUESDAY


def test_a_run_cut_off_midway_is_caught_up(db_engine, four_a_week):
    add_run(db_engine, "running")
    assert missed_daily_run(four_a_week, at(four_a_week, TUESDAY, 9), db_engine) == TUESDAY


@pytest.mark.parametrize("status", ["complete", "failed"])
def test_a_finished_or_failed_run_is_left_alone(db_engine, four_a_week, status):
    add_run(db_engine, status)
    assert missed_daily_run(four_a_week, at(four_a_week, TUESDAY, 9), db_engine) is None


def test_before_the_run_time_the_schedule_handles_it(db_engine, four_a_week):
    # the PC wakes at 04:45; the 05:00 schedule runs the day, not the catch-up
    assert missed_daily_run(four_a_week, at(four_a_week, TUESDAY, 4, 45), db_engine) is None


def test_no_catch_up_on_a_day_without_a_run(db_engine, four_a_week):
    monday = date(2026, 10, 19)
    assert missed_daily_run(four_a_week, at(four_a_week, monday, 9), db_engine) is None
