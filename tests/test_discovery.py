from datetime import datetime
from zoneinfo import ZoneInfo

from src.discovery import production_target_day


TZ = ZoneInfo("America/Guayaquil")


def test_target_days() -> None:
    assert production_target_day(datetime(2026, 8, 6, 15, tzinfo=TZ)).isoformat() == "2026-08-07"
    assert production_target_day(datetime(2026, 8, 7, 15, tzinfo=TZ)).isoformat() == "2026-08-08"
    assert production_target_day(datetime(2026, 8, 8, 15, tzinfo=TZ)).isoformat() == "2026-08-09"


def test_no_run_days() -> None:
    for day in (2, 3, 4, 5):  # domingo a miércoles de esa semana
        assert production_target_day(datetime(2026, 8, day, 15, tzinfo=TZ)) is None

