from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from datetime import date, datetime, time, timezone
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from icalendar import Calendar, Event, Timezone

import giants_official


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / "giants.ics"
GAMES_PATH = ROOT / "data" / "games.json"
SNAPSHOT_DIRECTORY = ROOT / "data" / "snapshots"
CANCELLATION_DIRECTORY = ROOT / "data" / "cancellations"
LOCAL_STADIUM_PATH = ROOT / "data" / "local-stadium.env"
LOCAL_URL_PATH = ROOT / "data" / "local-url.env"
JST = ZoneInfo("Asia/Tokyo")
MATCHUP_PATTERN = re.compile(r"^\s*(.+?)\s+@\s+(.+?)\s*$")
LOCAL_STADIUM_PATTERN = re.compile(r"(\d{4}-\d{2}-\d{2})\s*=\s*(.+)")
REGULAR_SEASON_GAMES_PER_MATCHUP = 25
INTERLEAGUE_GAMES_PER_MATCHUP = 3
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
HOME_STADIUMS_BY_TEAM = {
    TEAM_NAMES[team]: stadium for team, stadium in HOME_STADIUMS.items()
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


def save_games(events: dict[str, Event]) -> None:
    records = sorted(
        (event_to_record(event) for event in events.values()),
        key=lambda record: (record["start"], record["uid"]),
    )
    write_json(GAMES_PATH, {"schema_version": 1, "events": records})


def load_snapshot(year: int) -> dict[str, Event]:
    path = SNAPSHOT_DIRECTORY / f"snapshot-giants-{year}.json"
    if not path.exists():
        raise FileNotFoundError(f"スナップショットがありません: {path.relative_to(ROOT)}")
    contents = json.loads(path.read_text(encoding="utf-8"))
    return {
        record["uid"]: Event.from_ical(record["ical"].encode("utf-8"))
        for record in contents["events"]
    }


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


def load_local_url_overrides() -> dict[str, str]:
    if not LOCAL_URL_PATH.exists():
        return {}

    overrides: dict[str, str] = {}
    for line_number, raw_line in enumerate(
        LOCAL_URL_PATH.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = re.split(r"\s+=\s+", line)
        if len(parts) != 2:
            raise ValueError(f"{LOCAL_URL_PATH.name}:{line_number} の形式が不正です")
        for value in parts:
            try:
                url = urlsplit(value)
                valid = url.scheme in {"http", "https"} and url.hostname and url.port != 0
            except ValueError as error:
                raise ValueError(f"{LOCAL_URL_PATH.name}:{line_number} のURLが不正です") from error
            if not valid or any(char.isspace() for char in value):
                raise ValueError(f"{LOCAL_URL_PATH.name}:{line_number} のURLが不正です")
        source, replacement = parts
        if source in overrides:
            raise ValueError(f"{LOCAL_URL_PATH.name}:{line_number} の元URLが重複しています")
        overrides[source] = replacement
    return overrides


def normalize_team_name(team: str) -> str:
    return re.sub(r"\s+\(\d+\)$", "", team).strip()


def extract_score(team: str) -> int | None:
    match = re.search(r"\s+\((\d+)\)$", team)
    return int(match.group(1)) if match else None


def matchup_key(event: Event) -> tuple[str, str, str] | None:
    match = MATCHUP_PATTERN.match(str(event.get("SUMMARY", "")))
    if not match:
        return None
    away, home = (
        TEAM_NAMES.get(normalize_team_name(team), normalize_team_name(team))
        for team in match.groups()
    )
    game_date = event_start(event).astimezone(JST).date().isoformat()
    return game_date, away, home


def has_score(event: Event) -> bool:
    match = MATCHUP_PATTERN.match(str(event.get("SUMMARY", "")))
    return bool(match and all(extract_score(team) is not None for team in match.groups()))


def game_priority(event: Event) -> tuple[bool, bool, bool]:
    return (
        has_score(event),
        isinstance(event.decoded("DTSTART"), datetime),
        str(event.get("X-GIANTS-CALENDAR-SOURCE", "")) == "npb",
    )


def select_games(events: dict[str, Event]) -> dict[str, Event]:
    selected: dict[str, Event] = {}
    matchups: dict[tuple[str, str, str], str] = {}
    npb_venues: dict[tuple[str, str, str], Event] = {}
    for uid, event in sorted(events.items()):
        key = matchup_key(event)
        if key is None:
            selected[uid] = event
            continue
        if str(event.get("X-GIANTS-CALENDAR-SOURCE", "")) == "npb" and event.get("LOCATION"):
            previous_venue = npb_venues.get(key)
            if previous_venue is None or game_priority(event) > game_priority(previous_venue):
                npb_venues[key] = event
        previous_uid = matchups.get(key)
        if previous_uid is not None:
            previous = selected[previous_uid]
            if game_priority(event) <= game_priority(previous):
                continue
            del selected[previous_uid]
        selected[uid] = event
        matchups[key] = uid
    for key, uid in matchups.items():
        event = selected[uid]
        if key in npb_venues and str(event.get("X-GIANTS-CALENDAR-SOURCE", "")) != "npb":
            event = copy.deepcopy(event)
            event["LOCATION"] = copy.deepcopy(npb_venues[key]["LOCATION"])
            event["X-GIANTS-CALENDAR-NPB-LOCATION"] = "true"
            selected[uid] = event
    return selected


def validate_cancellations(contents: object, year: int) -> list[dict[str, str]]:
    if not isinstance(contents, dict) or contents.get("schema_version") != 1:
        raise ValueError("中止試合 JSON の schema_version が不正です")
    records = contents.get("games")
    if not isinstance(records, list):
        raise ValueError("中止試合 JSON に games がありません")
    games: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for record in records:
        if not isinstance(record, dict) or any(
            not isinstance(record.get(field), str)
            for field in ("date", "away", "home", "status")
        ):
            raise ValueError("中止試合 JSON の試合情報が不正です")
        game_date, away, home, status = (
            record["date"], record["away"], record["home"], record["status"]
        )
        try:
            parsed_date = date.fromisoformat(game_date)
        except ValueError as error:
            raise ValueError("中止試合 JSON の日付が不正です") from error
        if (
            parsed_date.isoformat() != game_date
            or parsed_date.year != year
            or away not in TEAM_NAMES.values()
            or home not in TEAM_NAMES.values()
            or away == home
            or status != "中止"
        ):
            raise ValueError("中止試合 JSON の日付、対戦カード、または状態が不正です")
        key = (game_date, away, home)
        if key in seen:
            raise ValueError("中止試合 JSON に重複があります")
        seen.add(key)
        games.append({"date": game_date, "away": away, "home": home, "status": status})
    return games


def load_cancellations(year: int) -> list[dict[str, str]]:
    path = CANCELLATION_DIRECTORY / f"cancellations-{year}.json"
    if not path.exists():
        print(f"No cancellation data for {year}; no confirmed cancellations will be excluded.", file=sys.stderr)
        return []
    return validate_cancellations(json.loads(path.read_text(encoding="utf-8")), year)


def filter_games(
    events: dict[str, Event], cancellations: list[dict[str, str]]
) -> dict[str, Event]:
    cancelled = {(game["date"], game["away"], game["home"]) for game in cancellations}
    return {uid: event for uid, event in events.items() if matchup_key(event) not in cancelled}


def regular_season_end(events: list[Event]) -> datetime | None:
    expected = {
        name: (
            INTERLEAGUE_GAMES_PER_MATCHUP
            if name in PACIFIC_LEAGUE_TEAMS
            else REGULAR_SEASON_GAMES_PER_MATCHUP
        )
        for name in TEAM_NAMES.values()
        if name != TEAM_NAMES["Yomiuri"]
    }
    completed = dict.fromkeys(expected, 0)
    seen: set[tuple[datetime, str, str]] = set()
    for event in sorted(events, key=event_start):
        match = MATCHUP_PATTERN.match(str(event.get("SUMMARY", "")))
        if not match:
            continue
        raw_away, raw_home = match.groups()
        if extract_score(raw_away) is None or extract_score(raw_home) is None:
            continue
        away, home = (
            TEAM_NAMES.get(normalize_team_name(team), normalize_team_name(team))
            for team in (raw_away, raw_home)
        )
        if TEAM_NAMES["Yomiuri"] not in (away, home):
            continue
        opponent = away if home == TEAM_NAMES["Yomiuri"] else home
        if opponent not in expected:
            continue
        start = event_start(event)
        identity = (start, away, home)
        if identity in seen:
            continue
        seen.add(identity)
        completed[opponent] += 1
        if completed[opponent] > expected[opponent]:
            print(
                f"CS classification skipped: {opponent} exceeds its "
                "regular-season game count before all 143 games are complete.",
                file=sys.stderr,
            )
            return None
        if completed == expected:
            return start
    return None


def update_summary(
    event, counters: dict[tuple[int, tuple[str, str]], int], *, is_cs: bool = False
) -> None:
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
    counter_key = (start.astimezone(JST).year, matchup)
    counters[counter_key] = counters.get(counter_key, 0) + 1
    game_number = counters[counter_key]
    if is_cs:
        title = f"【CS】{home_name} vs {away_name} 第{game_number}戦"
    else:
        subtitle = " 【交流戦】" if {home_name, away_name} & PACIFIC_LEAGUE_TEAMS else ""
        title = f"{home_name} vs {away_name}{subtitle} {game_number}回戦"

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
        return

    home = normalize_team_name(raw_home)
    home_stadium = HOME_STADIUMS.get(home) or HOME_STADIUMS_BY_TEAM.get(home)
    if (
        (
            str(event.get("X-GIANTS-CALENDAR-SOURCE", "")) == "npb"
            or str(event.get("X-GIANTS-CALENDAR-NPB-LOCATION", "")) == "true"
            or str(event.get("X-GIANTS-CALENDAR-OFFICIAL-LOCATION", "")) == "true"
        )
        and event.get("LOCATION")
    ):
        if home_stadium and str(event["LOCATION"]) == home_stadium.partition(",")[0]:
            event["LOCATION"] = home_stadium
        return
    if home_stadium:
        event["LOCATION"] = home_stadium


def build_calendar(
    events: list[Event], year: int, local_stadiums: dict[date, str]
) -> Calendar:
    calendar = Calendar()
    calendar.add("PRODID", "-//radicalgrimoire//Giants Calendar//JA")
    calendar.add("VERSION", "2.0")
    calendar.add("CALSCALE", "GREGORIAN")
    calendar.add("X-WR-CALNAME", "Yomiuri Giants")
    calendar.add("X-WR-TIMEZONE", "Asia/Tokyo")
    calendar.add_component(Timezone.from_tzinfo(JST))

    events = sorted(
        (event for event in events if event_start(event).astimezone(JST).year == year),
        key=event_start,
    )
    season_end = regular_season_end(events)
    counters: dict[tuple[int, tuple[str, str]], int] = {}
    cs_counters: dict[tuple[int, tuple[str, str]], int] = {}
    for event in events:
        is_cs = season_end is not None and event_start(event) > season_end
        output_event = copy.deepcopy(event)
        update_location(output_event, local_stadiums)
        update_summary(
            output_event, cs_counters if is_cs else counters, is_cs=is_cs
        )
        calendar.add_component(output_event)

    return calendar


def generate_calendar(year: int) -> tuple[dict[str, Event], Calendar]:
    days = giants_official.load_months(year)
    if days and not (SNAPSHOT_DIRECTORY / f"snapshot-giants-{year}.json").exists():
        games = {}
    else:
        games = select_games(load_snapshot(year))
    if any(event_start(event).astimezone(JST).year != year for event in games.values()):
        raise ValueError(f"{year}年のスナップショットに別の年の試合があります")
    previous = giants_official.previous_uids(GAMES_PATH, matchup_key) if days else {}
    url_overrides = load_local_url_overrides()
    games, descriptions = giants_official.merge_games(
        games, days, matchup_key, previous, url_overrides
    )
    games = filter_games(games, load_cancellations(year))
    calendar = build_calendar(
        list(games.values()), year, load_local_stadiums()
    )
    giants_official.add_calendar_details(calendar, days, descriptions, url_overrides)
    return games, calendar


def snapshot_years() -> list[int]:
    years = []
    for path in SNAPSHOT_DIRECTORY.glob("snapshot-giants-*.json"):
        match = re.fullmatch(r"snapshot-giants-(\d{4})\.json", path.name)
        if match is None:
            raise ValueError(f"スナップショットのファイル名が不正です: {path.name}")
        years.append(int(match.group(1)))
    years = sorted(set(years) | giants_official.snapshot_years())
    if not years:
        raise FileNotFoundError(f"スナップショットがありません: {SNAPSHOT_DIRECTORY}")
    return years


def generate_all_calendars() -> tuple[dict[str, Event], Calendar]:
    years = snapshot_years()
    all_games: dict[str, Event] = {}
    combined = build_calendar([], years[0], {})
    for year in years:
        games, calendar = generate_calendar(year)
        duplicates = all_games.keys() & games.keys()
        if duplicates:
            raise ValueError(f"年度をまたぐ試合UIDの重複があります: {sorted(duplicates)}")
        all_games.update(games)
        for component in calendar.subcomponents:
            if component.name == "VEVENT":
                combined.add_component(component)
    return all_games, combined


def main() -> None:
    parser = argparse.ArgumentParser(description="巨人戦ICSを生成します。")
    parser.add_argument("--year", type=int, help="指定年度のみ生成")
    parser.add_argument("--output", type=Path, help="生成するICSファイルの出力先")
    args = parser.parse_args()

    if args.year is not None and args.output is None:
        parser.error("年度別に生成する場合は --output を指定してください。")

    output_path = args.output or OUTPUT_PATH
    if not output_path.is_absolute():
        output_path = ROOT / output_path
    output_path = output_path.resolve()

    if args.year is not None and output_path == OUTPUT_PATH.resolve():
        parser.error("年度別ICSの出力先に配信用ICSを指定できません。")

    games, calendar = (
        generate_calendar(args.year) if args.year is not None else generate_all_calendars()
    )
    if args.year is None and output_path == OUTPUT_PATH.resolve():
        save_games(games)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(calendar.to_ical())
    print(f"Generated {output_path.relative_to(ROOT)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Calendar generation failed: {error}", file=sys.stderr)
        raise
