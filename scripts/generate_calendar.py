from __future__ import annotations

import copy
import re
import sys
from datetime import date, datetime, time, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from icalendar import Calendar


SOURCE_URL = (
    "https://calendar.google.com/calendar/ical/"
    "npb_-m-0132%257e_h_%2559omiuri%2B%2547iants%23sports%40group.v.calendar.google.com/"
    "public/basic.ics"
)
ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / "giants.ics"
SOURCE_DIRECTORY = ROOT / "data" / "source"
JST = ZoneInfo("Asia/Tokyo")
MATCHUP_PATTERN = re.compile(r"^\s*(.+?)\s+@\s+(.+?)\s*$")

TEAM_NAMES = {
    "Yomiuri": "読売ジャイアンツ",
    "Hanshin": "阪神タイガース",
    "Hiroshima": "広島東洋カープ",
    "Chunichi": "中日ドラゴンズ",
    "Yokohama DeNA": "横浜DeNAベイスターズ",
    "Yakult": "東京ヤクルトスワローズ",
    "Fukuoka SoftBank": "福岡ソフトバンクホークス",
    "Hokkaido Nippon-Ham": "北海道日本ハムファイターズ",
    "Chiba Lotte": "千葉ロッテマリーンズ",
    "Tohoku Rakuten": "東北楽天ゴールデンイーグルス",
    "Orix": "オリックス・バファローズ",
    "Saitama Seibu": "埼玉西武ライオンズ",
}


def fetch_source() -> bytes:
    request = Request(SOURCE_URL, headers={"User-Agent": "giants-calendar/1.0"})
    with urlopen(request, timeout=30) as response:
        return response.read()


def event_start(event) -> datetime:
    value = event.decoded("DTSTART")
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=timezone.utc)
    raise ValueError("VEVENT に DTSTART がありません")


def update_summary(event, counters: dict[tuple[int, tuple[str, str]], int]) -> None:
    summary = str(event.get("SUMMARY", ""))
    match = MATCHUP_PATTERN.match(summary)
    if not match:
        return

    away, home = match.groups()
    start = event_start(event)
    matchup = tuple(sorted((away, home)))
    counter_key = (start.year, matchup)
    counters[counter_key] = counters.get(counter_key, 0) + 1

    home_name = TEAM_NAMES.get(home, home)
    away_name = TEAM_NAMES.get(away, away)
    event["SUMMARY"] = f"{home_name} 対 {away_name} {counters[counter_key]}回戦"


def build_calendar(source: Calendar) -> Calendar:
    calendar = Calendar()
    calendar.add("PRODID", "-//radicalgrimoire//Giants Calendar//JA")
    calendar.add("VERSION", "2.0")
    calendar.add("CALSCALE", "GREGORIAN")
    calendar.add("X-WR-CALNAME", "読売ジャイアンツ日程")
    calendar.add("X-WR-TIMEZONE", "Asia/Tokyo")

    events = sorted(
        (component for component in source.walk() if component.name == "VEVENT"),
        key=event_start,
    )
    counters: dict[tuple[int, tuple[str, str]], int] = {}
    for event in events:
        output_event = copy.deepcopy(event)
        update_summary(output_event, counters)
        calendar.add_component(output_event)

    for component in source.subcomponents:
        if component.name == "VTIMEZONE":
            calendar.add_component(copy.deepcopy(component))
    return calendar


def save_weekly_snapshot(source_data: bytes) -> None:
    if datetime.now(JST).weekday() != 0:
        return
    SOURCE_DIRECTORY.mkdir(parents=True, exist_ok=True)
    snapshot_path = SOURCE_DIRECTORY / f"{datetime.now(JST):%Y-%m-%d}.ics"
    snapshot_path.write_bytes(source_data)


def main() -> None:
    source_data = fetch_source()
    source = Calendar.from_ical(source_data)
    save_weekly_snapshot(source_data)
    OUTPUT_PATH.write_bytes(build_calendar(source).to_ical())
    print(f"Generated {OUTPUT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Calendar generation failed: {error}", file=sys.stderr)
        raise
