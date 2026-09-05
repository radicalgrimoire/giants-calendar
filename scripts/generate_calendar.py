from __future__ import annotations

import copy
import json
import re
import sys
from datetime import date, datetime, time, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from icalendar import Calendar, Event


SOURCE_URL = (
    "https://calendar.google.com/calendar/ical/"
    "npb_-m-0132%257e_h_%2559omiuri%2B%2547iants%23sports%40group.v.calendar.google.com/"
    "public/basic.ics"
)
ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / "giants.ics"
BACKLOG_DIRECTORY = ROOT / "backlog"
GAMES_PATH = ROOT / "data" / "games.json"
SNAPSHOT_DIRECTORY = ROOT / "data" / "snapshots"
LOCAL_STADIUM_PATH = ROOT / "data" / "local-stadium.env"
JST = ZoneInfo("Asia/Tokyo")
MATCHUP_PATTERN = re.compile(r"^\s*(.+?)\s+@\s+(.+?)\s*$")
LOCAL_STADIUM_PATTERN = re.compile(r"(\d{4}-\d{2}-\d{2})\s*=\s*(.+)")
HOME_STADIUMS = {
    "Yomiuri": "東京ドーム, 日本、〒112-0004 東京都文京区後楽１丁目３−６１",
    "Hanshin": "阪神甲子園球場, 日本、〒663-8152 兵庫県西宮市甲子園町１−８２",
    "Hiroshima": "MAZDA Zoom-Zoom スタジアム広島(広島市民球場), 日本、〒732-0803 広島県広島市南区南蟹屋２丁目３−１",
    "Chunichi": "バンテリンドーム ナゴヤ, 日本、〒461-0047 愛知県名古屋市東区大幸南１丁目１−１",
    "DeNA": "横浜スタジアム, 日本、〒231-0022 神奈川県横浜市中区横浜公園",
    "Yakult": "明治神宮野球場, 日本、〒160-0013 東京都新宿区霞ヶ丘町３−１",
    "SoftBank": "みずほPayPayドーム福岡, 日本、〒810-8660 福岡県福岡市中央区地行浜２丁目２−２",
    "Nippon-Ham": "エスコンフィールドHOKKAIDO, 日本、〒061-1116 北海道北広島市Ｆビレッジ１番地",
    "Lotte": "ZOZOマリンスタジアム, 日本、〒261-0022 千葉県千葉市美浜区美浜１",
    "Rakuten": "楽天モバイル 最強パーク宮城, 日本、〒983-0045 宮城県仙台市宮城野区宮城野２丁目１１−６",
    "Orix": "京セラドーム大阪, 日本、〒550-0023 大阪府大阪市西区千代崎３丁目中２−中２−１",
    "Seibu": "ベルーナドーム, 日本、〒359-1153 埼玉県所沢市上山口２１３５",
}

TEAM_NAMES = {
    "Yomiuri": "読売ジャイアンツ",
    "Hanshin": "阪神タイガース",
    "Hiroshima": "広島東洋カープ",
    "Chunichi": "中日ドラゴンズ",
    "DeNA": "横浜DeNAベイスターズ",
    "Yakult": "東京ヤクルトスワローズ",
    "SoftBank": "福岡ソフトバンクホークス",
    "Nippon-Ham": "北海道日本ハムファイターズ",
    "Lotte": "千葉ロッテマリーンズ",
    "Rakuten": "東北楽天ゴールデンイーグルス",
    "Orix": "オリックス・バファローズ",
    "Seibu": "埼玉西武ライオンズ",
}
PACIFIC_LEAGUE_TEAMS = {
    "福岡ソフトバンクホークス",
    "北海道日本ハムファイターズ",
    "千葉ロッテマリーンズ",
    "東北楽天ゴールデンイーグルス",
    "オリックス・バファローズ",
    "埼玉西武ライオンズ",
}
TEAM_ABBREVIATIONS = {
    "読売ジャイアンツ": "G",
    "阪神タイガース": "T",
    "広島東洋カープ": "C",
    "中日ドラゴンズ": "D",
    "横浜DeNAベイスターズ": "DB",
    "東京ヤクルトスワローズ": "S",
    "福岡ソフトバンクホークス": "H",
    "北海道日本ハムファイターズ": "F",
    "千葉ロッテマリーンズ": "M",
    "東北楽天ゴールデンイーグルス": "E",
    "オリックス・バファローズ": "Bs",
    "埼玉西武ライオンズ": "L",
}
MATCHUP_INITIAL_COUNTS = {
    (2026, tuple(sorted(("読売ジャイアンツ", "中日ドラゴンズ")))): 8,
    (2026, tuple(sorted(("読売ジャイアンツ", "広島東洋カープ")))): 7,
    (2026, tuple(sorted(("読売ジャイアンツ", "横浜DeNAベイスターズ")))): 9,
    (2026, tuple(sorted(("読売ジャイアンツ", "東京ヤクルトスワローズ")))): 11,
    (2026, tuple(sorted(("読売ジャイアンツ", "阪神タイガース")))): 11,
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


def event_uid(event) -> str:
    uid = event.get("UID")
    if uid is None:
        raise ValueError("VEVENT に UID がありません")
    return str(uid)


def event_to_record(event) -> dict[str, str]:
    return {
        "uid": event_uid(event),
        "start": event_start(event).isoformat(),
        "ical": event.to_ical().decode("utf-8"),
    }


def write_json(path: Path, contents: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(contents, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def load_games() -> dict[str, Event]:
    if not GAMES_PATH.exists():
        return {}
    contents = json.loads(GAMES_PATH.read_text(encoding="utf-8"))
    return {
        record["uid"]: Event.from_ical(record["ical"].encode("utf-8"))
        for record in contents["events"]
    }


def save_games(events: dict[str, Event]) -> None:
    records = sorted(
        (event_to_record(event) for event in events.values()),
        key=lambda record: (record["start"], record["uid"]),
    )
    write_json(GAMES_PATH, {"schema_version": 1, "events": records})


def save_weekly_snapshot(events: list[Event]) -> None:
    now = datetime.now(JST)
    if now.weekday() != 0:
        return
    records = sorted(
        (event_to_record(event) for event in events),
        key=lambda record: (record["start"], record["uid"]),
    )
    snapshot_path = SNAPSHOT_DIRECTORY / f"games-{now:%Y-%m-%d}.json"
    write_json(snapshot_path, {"schema_version": 1, "events": records})


def merge_source_events(source_events: list[Event], games: dict[str, Event]) -> dict[str, Event]:
    observed_uids = {event_uid(event) for event in source_events}
    merged = {uid: copy.deepcopy(event) for uid, event in games.items()}
    for event in source_events:
        merged[event_uid(event)] = copy.deepcopy(event)

    now = datetime.now(timezone.utc)
    for uid, event in list(merged.items()):
        if uid not in observed_uids and event_start(event) >= now:
            del merged[uid]
    return merged


def current_calendar_year() -> int:
    return datetime.now(JST).year


def load_local_stadiums() -> dict[date, str]:
    if not LOCAL_STADIUM_PATH.exists():
        return {}

    stadiums: dict[date, str] = {}
    for line_number, raw_line in enumerate(
        LOCAL_STADIUM_PATH.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = LOCAL_STADIUM_PATTERN.fullmatch(line)
        if not match:
            raise ValueError(
                f"{LOCAL_STADIUM_PATH.name}:{line_number} の形式が不正です"
            )
        game_date, stadium = match.groups()
        stadiums[date.fromisoformat(game_date)] = stadium.strip()
    return stadiums


def archive_previous_calendar() -> None:
    now = datetime.now(JST)
    if (now.month, now.day) != (1, 1) or not OUTPUT_PATH.exists():
        return
    archive_path = BACKLOG_DIRECTORY / f"giants-{now.year - 1}.ics"
    if archive_path.exists():
        return
    BACKLOG_DIRECTORY.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.replace(archive_path)


def normalize_team_name(team: str) -> str:
    return re.sub(r"\s+\(\d+\)$", "", team).strip()


def extract_score(team: str) -> int | None:
    match = re.search(r"\s+\((\d+)\)$", team)
    return int(match.group(1)) if match else None


def update_summary(event, counters: dict[tuple[int, tuple[str, str]], int]) -> None:
    summary = str(event.get("SUMMARY", ""))
    match = MATCHUP_PATTERN.match(summary)
    if not match:
        return

    raw_away, raw_home = match.groups()
    away = normalize_team_name(raw_away)
    home = normalize_team_name(raw_home)
    start = event_start(event)
    home_name = TEAM_NAMES.get(home, home)
    away_name = TEAM_NAMES.get(away, away)
    matchup = tuple(sorted((away_name, home_name)))
    counter_key = (start.year, matchup)
    counters[counter_key] = counters.get(
        counter_key, MATCHUP_INITIAL_COUNTS.get(counter_key, 0)
    ) + 1
    subtitle = " 【交流戦】" if {home_name, away_name} & PACIFIC_LEAGUE_TEAMS else ""
    title = f"{home_name} vs {away_name}{subtitle} {counters[counter_key]}回戦"

    away_score = extract_score(raw_away)
    home_score = extract_score(raw_home)
    if away_score is not None and home_score is not None:
        title += f" （{home_score} - {away_score}）"
        description = str(event.get("DESCRIPTION", "")).strip()
        home_abbreviation = TEAM_ABBREVIATIONS.get(home_name, home_name)
        away_abbreviation = TEAM_ABBREVIATIONS.get(away_name, away_name)
        giants_score = home_score if home_name == "読売ジャイアンツ" else away_score
        opponent_score = away_score if home_name == "読売ジャイアンツ" else home_score
        if giants_score > opponent_score:
            result_status = "勝利"
        elif giants_score < opponent_score:
            result_status = "敗北"
        else:
            result_status = "引き分け"
        result = "\n".join(
            [
                f"試合結果：{home_abbreviation}{home_score} - {away_abbreviation}{away_score} {result_status}",
                f"（HOME）{home_name}",
                f"（VISIT）{away_name}",
            ]
        )
        event["DESCRIPTION"] = f"{description}\n\n{result}".strip()
    event["SUMMARY"] = title


def update_location(event, local_stadiums: dict[date, str]) -> None:
    summary = str(event.get("SUMMARY", ""))
    match = MATCHUP_PATTERN.match(summary)
    if not match:
        return

    _, raw_home = match.groups()
    game_date = event_start(event).astimezone(JST).date()
    stadium = local_stadiums.get(game_date)
    if stadium is not None:
        event["LOCATION"] = stadium
    elif stadium := HOME_STADIUMS.get(normalize_team_name(raw_home)):
        event["LOCATION"] = stadium


def build_calendar(
    events: list[Event], timezones: list, year: int, local_stadiums: dict[date, str]
) -> Calendar:
    calendar = Calendar()
    calendar.add("PRODID", "-//radicalgrimoire//Giants Calendar//JA")
    calendar.add("VERSION", "2.0")
    calendar.add("CALSCALE", "GREGORIAN")
    calendar.add("X-WR-CALNAME", f"読売ジャイアンツ日程 {year}")
    calendar.add("X-WR-TIMEZONE", "Asia/Tokyo")

    events = sorted(
        (event for event in events if event_start(event).astimezone(JST).year == year),
        key=event_start,
    )
    counters: dict[tuple[int, tuple[str, str]], int] = {}
    for event in events:
        output_event = copy.deepcopy(event)
        update_location(output_event, local_stadiums)
        update_summary(output_event, counters)
        calendar.add_component(output_event)

    for timezone_component in timezones:
        calendar.add_component(copy.deepcopy(timezone_component))
    return calendar


def main() -> None:
    source_data = fetch_source()
    source = Calendar.from_ical(source_data)
    source_events = [
        component for component in source.walk() if component.name == "VEVENT"
    ]
    save_weekly_snapshot(source_events)
    games = merge_source_events(source_events, load_games())
    save_games(games)
    timezones = [
        component for component in source.subcomponents if component.name == "VTIMEZONE"
    ]
    year = current_calendar_year()
    archive_previous_calendar()
    OUTPUT_PATH.write_bytes(
        build_calendar(
            list(games.values()), timezones, year, load_local_stadiums()
        ).to_ical()
    )
    print(f"Generated {OUTPUT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Calendar generation failed: {error}", file=sys.stderr)
        raise
