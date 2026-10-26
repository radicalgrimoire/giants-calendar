#!/usr/bin/env python3
"""配信用カレンダー内の同日複数試合を検出する。"""

from __future__ import annotations

import sys
from collections import defaultdict
from datetime import date, datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from icalendar import Calendar, Event


ROOT = Path(__file__).resolve().parents[1]
CALENDAR_PATH = ROOT / "giants.ics"
JST = ZoneInfo("Asia/Tokyo")


def event_start(event: Event) -> datetime:
    value = event.decoded("DTSTART")
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=timezone.utc)
    raise ValueError("VEVENT に DTSTART がありません")


def duplicate_dates(calendar: Calendar) -> dict[date, list[Event]]:
    events_by_date: dict[date, list[Event]] = defaultdict(list)
    for component in calendar.walk():
        if component.name == "VEVENT":
            events_by_date[event_start(component).astimezone(JST).date()].append(component)
    return {
        game_date: events
        for game_date, events in events_by_date.items()
        if len(events) > 1
    }


def main() -> None:
    if not CALENDAR_PATH.exists():
        raise FileNotFoundError(f"カレンダーファイルがありません: {CALENDAR_PATH.relative_to(ROOT)}")

    duplicates = duplicate_dates(Calendar.from_ical(CALENDAR_PATH.read_bytes()))
    if not duplicates:
        print("同一日に複数の試合はありません。")
        return

    print("同一日に複数の試合が検出されました:", file=sys.stderr)
    for game_date, events in sorted(duplicates.items()):
        print(f"- {game_date}:", file=sys.stderr)
        for event in sorted(events, key=event_start):
            start = event_start(event).astimezone(JST).strftime("%H:%M")
            summary = str(event.get("SUMMARY", ""))
            uid = str(event.get("UID", ""))
            print(f"  - {start} {summary} (UID: {uid})", file=sys.stderr)
    raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Duplicate game date check failed: {error}", file=sys.stderr)
        raise
