"""List 2027 Giants Kanto away games."""

import argparse
import re
import sys
from datetime import date, datetime
from pathlib import Path
from urllib.request import urlopen
from zoneinfo import ZoneInfo

from icalendar import Calendar

from japanese_holidays import is_weekend_or_holiday, load_holidays

CALENDAR_URL = "https://raw.githubusercontent.com/radicalgrimoire/giants-calendar/main/giants.ics"
JST = ZoneInfo("Asia/Tokyo")
GIANTS = "読売ジャイアンツ"
KANTO = ("東京都", "神奈川県", "千葉県", "埼玉県", "茨城県", "栃木県", "群馬県")
PREFECTURE = re.compile(r"東京都|北海道|京都府|大阪府|[^\s、,]{2,3}県")
MATCHUP = re.compile(r"^(?:【CS】)?(.+?) vs (.+?)(?:\s|$)")
WEEKDAYS = "月火水木金土日"


def select_games(calendar: Calendar) -> list[tuple[date, str]]:
    games = []
    for event in calendar.walk("VEVENT"):
        start = event.decoded("DTSTART")
        if isinstance(start, datetime):
            start = start.replace(tzinfo=JST) if start.tzinfo is None else start.astimezone(JST)
            game_date = start.date()
        elif isinstance(start, date):
            game_date = start
        else:
            raise ValueError(f"不正な DTSTART: {start!r}")

        if game_date.year != 2027:
            continue
        if str(event.get("STATUS", "")).upper() == "CANCELLED":
            continue

        summary = str(event.get("SUMMARY", ""))
        match = MATCHUP.match(summary)
        if not match:
            print(f"警告: 対戦カードを判定できません: {game_date} {summary}", file=sys.stderr)
            continue
        if match.group(2) != GIANTS or match.group(1) == GIANTS:
            continue

        location = str(event.get("LOCATION", ""))
        if not PREFECTURE.search(location):
            print(f"警告: 球場の都道府県を判定できません: {game_date} {summary} {location}", file=sys.stderr)
            continue
        if "東京ドーム" in location or not any(prefecture in location for prefecture in KANTO):
            continue
        games.append((game_date, match.group(1)))
    return sorted(games)


def main() -> None:
    parser = argparse.ArgumentParser(description="2027年の関東ビジター戦を平日と土日祝日に分けて表示")
    parser.add_argument("--ics", type=Path, help="公開カレンダーの代わりにローカルのICSを使用")
    parser.add_argument("--holidays", type=Path, help="内閣府の公開データの代わりにローカルの祝日CSVを使用")
    args = parser.parse_args()

    if args.ics is None:
        with urlopen(CALENDAR_URL, timeout=30) as response:
            contents = response.read()
    else:
        contents = args.ics.read_bytes()

    holidays = load_holidays(args.holidays, 2027)
    games = select_games(Calendar.from_ical(contents))
    if not games:
        print("条件に一致する試合は見つかりませんでした。警告がある場合は確認してください。")
        return
    for heading, weekend in (("平日", False), ("土日祝日", True)):
        if weekend:
            print()
        print(f"【{heading}】")
        selected = [(game_date, opponent) for game_date, opponent in games
                    if is_weekend_or_holiday(game_date, holidays) == weekend]
        if not selected:
            print("（該当なし）")
        for game_date, opponent in selected:
            print(f"{game_date}（{WEEKDAYS[game_date.weekday()]}） vs {opponent}")


if __name__ == "__main__":
    main()
