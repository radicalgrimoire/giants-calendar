"""Count 2027 Giants games by opponent and weekday category."""

import argparse
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from urllib.request import urlopen

from icalendar import Calendar

from japanese_holidays import is_weekend_or_holiday, load_holidays
from weekend_away_games import CALENDAR_URL, GIANTS, JST, MATCHUP

YEAR = 2027


def count_games(calendar: Calendar, holidays: set[date]) -> dict[str, Counter[str]]:
    counts: dict[str, Counter[str]] = {}
    for event in calendar.walk("VEVENT"):
        start = event.decoded("DTSTART")
        if isinstance(start, datetime):
            start = start.replace(tzinfo=JST) if start.tzinfo is None else start.astimezone(JST)
            game_date = start.date()
        elif isinstance(start, date):
            game_date = start
        else:
            raise ValueError(f"不正な DTSTART: {start!r}")

        if game_date.year != YEAR or str(event.get("STATUS", "")).upper() == "CANCELLED":
            continue

        summary = str(event.get("SUMMARY", ""))
        match = MATCHUP.match(summary)
        if not match or (match.group(1) == GIANTS) == (match.group(2) == GIANTS):
            print(f"警告: 対戦相手を判定できません: {game_date} {summary}", file=sys.stderr)
            continue
        opponent = match.group(2) if match.group(1) == GIANTS else match.group(1)
        category = "weekend" if is_weekend_or_holiday(game_date, holidays) else "weekday"
        counts.setdefault(opponent, Counter())[category] += 1
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="2027年の試合を相手球団別に平日・週末＋祝日で集計")
    parser.add_argument("--ics", type=Path, help="公開カレンダーの代わりにローカルのICSを使用")
    parser.add_argument("--holidays", type=Path, help="内閣府の公開データの代わりにローカルの祝日CSVを使用")
    args = parser.parse_args()

    if args.ics is None:
        with urlopen(CALENDAR_URL, timeout=30) as response:
            contents = response.read()
    else:
        contents = args.ics.read_bytes()

    counts = count_games(Calendar.from_ical(contents), load_holidays(args.holidays, YEAR))
    if not counts:
        print("集計できる試合がありません。警告がある場合は確認してください。")
        return
    print(f"{YEAR}年 ジャイアンツの対戦球団別試合数")
    print("球団名（平日 / 週末＋祝日）\n")
    for opponent, games in sorted(counts.items()):
        weekday, weekend = games["weekday"], games["weekend"]
        print(f"{opponent}（{weekday}試合 / {weekend}試合）")
    weekday = sum(games["weekday"] for games in counts.values())
    weekend = sum(games["weekend"] for games in counts.values())
    print(f"合計（{weekday}試合 / {weekend}試合）")


if __name__ == "__main__":
    main()
