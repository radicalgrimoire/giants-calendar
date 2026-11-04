#!/usr/bin/env python3
"""配信対象の試合データ内の同日複数試合を検出する。"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from icalendar import Event


ROOT = Path(__file__).resolve().parents[1]
GAMES_PATH = ROOT / "data" / "games.json"
JST = ZoneInfo("Asia/Tokyo")


@dataclass(frozen=True)
class Game:
    uid: str
    start: datetime
    ical: str


def load_games(path: Path) -> list[Game]:
    contents = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(contents, dict) or contents.get("schema_version") != 1:
        raise ValueError("試合 JSON の schema_version が不正です")
    records = contents.get("events")
    if not isinstance(records, list):
        raise ValueError("試合 JSON の events が不正です")

    games = []
    for index, record in enumerate(records, start=1):
        if not isinstance(record, dict) or any(
            not isinstance(record.get(field), str) or not record[field]
            for field in ("uid", "start", "ical")
        ):
            raise ValueError(f"試合 JSON の events[{index}] が不正です")
        try:
            start = datetime.fromisoformat(record["start"])
        except ValueError as error:
            raise ValueError(f"試合 JSON の events[{index}] の開始日時が不正です") from error
        if start.utcoffset() is None:
            raise ValueError(f"試合 JSON の events[{index}] にタイムゾーンがありません")
        games.append(Game(uid=record["uid"], start=start, ical=record["ical"]))
    return games


def duplicate_dates(games: list[Game]) -> dict[date, list[Game]]:
    games_by_date: dict[date, list[Game]] = defaultdict(list)
    for game in games:
        games_by_date[game.start.astimezone(JST).date()].append(game)
    return {
        game_date: events
        for game_date, events in games_by_date.items()
        if len(events) > 1
    }


def main() -> None:
    duplicates = duplicate_dates(load_games(GAMES_PATH))
    if not duplicates:
        print("同一日に複数の試合はありません。")
        return

    print("同一日に複数の試合が検出されました:", file=sys.stderr)
    for game_date, games in sorted(duplicates.items()):
        print(f"- {game_date}:", file=sys.stderr)
        for game in sorted(games, key=lambda item: item.start):
            event = Event.from_ical(game.ical)
            start = event.decoded("DTSTART")
            label = (
                game.start.astimezone(JST).strftime("%H:%M")
                if isinstance(start, datetime)
                else "終日"
            )
            summary = str(event.get("SUMMARY", ""))
            print(f"  - {label} {summary} (UID: {game.uid})", file=sys.stderr)
    raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Duplicate game date check failed: {error}", file=sys.stderr)
        raise
