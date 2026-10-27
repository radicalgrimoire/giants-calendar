#!/usr/bin/env python3
"""前年の配信用カレンダーを退避し、新年分へ切り替える。"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from icalendar import Calendar

from generate_calendar import (
    JST,
    OUTPUT_PATH,
    current_calendar_year,
    generate_calendar,
    save_games,
)


ROOT = Path(__file__).resolve().parents[1]
BACKLOG_DIRECTORY = ROOT / "backlog"


def archive_previous_calendar(year: int) -> None:
    if not OUTPUT_PATH.exists():
        return

    archive_path = BACKLOG_DIRECTORY / f"giants-{year - 1}.ics"
    if archive_path.exists():
        return

    BACKLOG_DIRECTORY.mkdir(parents=True, exist_ok=True)
    calendar = Calendar.from_ical(OUTPUT_PATH.read_bytes())
    calendar["X-WR-CALNAME"] = f"Yomiuri Giants {year - 1}"
    archive_path.write_bytes(calendar.to_ical())


def main() -> None:
    now = datetime.now(JST)
    if (now.month, now.day) != (1, 1):
        raise RuntimeError("年始カレンダーの再作成は1月1日にだけ実行できます")

    year = current_calendar_year()
    games, calendar = generate_calendar(year)
    archive_previous_calendar(year)
    save_games(games)
    OUTPUT_PATH.write_bytes(calendar.to_ical())
    print(f"Renewed {OUTPUT_PATH.relative_to(ROOT)} for {year}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Calendar year renewal failed: {error}", file=sys.stderr)
        raise
