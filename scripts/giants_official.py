from __future__ import annotations

import copy
import json
import re
import sys
import unicodedata
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from icalendar import Event


JST = ZoneInfo("Asia/Tokyo")
DIRECTORY = Path(__file__).resolve().parents[1] / "data" / "snapshots-giants"
TEAMS = {
    "巨人": "読売ジャイアンツ", "読売": "読売ジャイアンツ",
    "阪神": "阪神タイガース", "中日": "中日ドラゴンズ",
    "DeNA": "横浜DeNAベイスターズ", "横浜": "横浜DeNAベイスターズ",
    "広島": "広島東洋カープ", "ヤクルト": "東京ヤクルトスワローズ",
    "ソフトバンク": "福岡ソフトバンクホークス",
    "日本ハム": "北海道日本ハムファイターズ", "ロッテ": "千葉ロッテマリーンズ",
    "楽天": "東北楽天ゴールデンイーグルス", "オリックス": "オリックス・バファローズ",
    "西武": "埼玉西武ライオンズ",
}


def snapshot_years() -> set[int]:
    years = set()
    for path in DIRECTORY.glob("*.json"):
        if path.name.startswith("detail-"):
            continue
        if not re.fullmatch(r"\d{4}(0[1-9]|1[0-2])\.json", path.name):
            raise ValueError(f"球団公式スナップショットのファイル名が不正です: {path}")
        years.add(int(path.stem[:4]))
    return years


def load_months(year: int) -> list[dict]:
    records = []
    for path in sorted(DIRECTORY.glob(f"{year}[0-1][0-9].json")):
        contents = json.loads(path.read_text(encoding="utf-8"))
        if contents.get("schema_version") != 1 or contents.get("month") != path.stem or not isinstance(contents.get("days"), list):
            raise ValueError(f"球団公式スナップショットが不正です: {path}")
        for day in contents["days"]:
            if not isinstance(day, dict) or not isinstance(day.get("date"), str):
                raise ValueError(f"球団公式日程の日付が不正です: {path}")
            parsed = date.fromisoformat(day["date"])
            if parsed.strftime("%Y%m") != path.stem:
                raise ValueError(f"球団公式日程の対象月が不正です: {path}")
            records.append(day)
    return records


def team_name(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).strip()
    return TEAMS.get(value, value)


def official_key(day: dict) -> tuple[str, str, str]:
    game = day["game"]
    if not isinstance(game, dict) or not all(isinstance(game.get(k), str) and game[k] for k in ("id", "home", "away")):
        raise ValueError(f"球団公式の試合情報が不正です: {day['date']}")
    return day["date"], team_name(game["away"]), team_name(game["home"])


def detail_data(game_id: str, game_date: str) -> dict | None:
    if not re.fullmatch(r"\d{8}_\d+_\d+", game_id):
        raise ValueError(f"球団公式の試合IDが不正です: {game_id}")
    path = DIRECTORY / f"detail-{game_id}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or data.get("id") != game_id or data.get("date") != game_date:
        raise ValueError(f"球団公式の試合詳細が不正です: {path}")
    start = datetime.fromisoformat(data["start"])
    end = datetime.fromisoformat(data["end"])
    if start.tzinfo is None or end.tzinfo is None or start.astimezone(JST).date().isoformat() != game_date or end <= start:
        raise ValueError(f"試合時刻が不正です: {path}")
    for field in ("home_starter", "away_starter"):
        value = data.get(field)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ValueError(f"先発投手が不正です: {path}")
    data["start"] = start.astimezone(JST)
    data["end"] = end.astimezone(JST)
    return data


def description(day: dict) -> str:
    lines = []
    events = day.get("events", [])
    if not isinstance(events, list):
        raise ValueError(f"イベント情報が不正です: {day['date']}")
    if events:
        lines.append("【当日のイベント】")
        for event in events:
            if not isinstance(event, dict) or not isinstance(event.get("title"), str) or not event["title"]:
                raise ValueError(f"イベント名が不正です: {day['date']}")
            lines.append(f"・{event['title']}")
    return "\n".join(lines)


def previous_uids(path: Path, matchup_key) -> dict:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or not isinstance(data.get("events"), list):
        raise ValueError(f"試合データが不正です: {path}")
    result = {}
    for record in data["events"]:
        event = Event.from_ical(record["ical"].encode("utf-8"))
        key = matchup_key(event)
        if key and key in result:
            raise ValueError(f"保存済みの試合が重複しています: {key}")
        if key:
            result[key] = str(event["UID"])
    return result


def new_game(day: dict, key: tuple[str, str, str]) -> Event:
    game = day["game"]
    if "読売ジャイアンツ" not in key[1:] or any(name not in TEAMS.values() for name in key[1:]):
        raise ValueError(f"球団公式の対戦相手を識別できません: {key}")
    start = scheduled_start(day) or date.fromisoformat(day["date"])
    event = Event()
    event.add("UID", f"giants-official-game-{game['id']}@giants-calendar.local")
    event.add("DTSTAMP", datetime.combine(date.fromisoformat(day["date"]), time.min, tzinfo=timezone.utc))
    event.add("DTSTART", start)
    event.add("DTEND", start + (timedelta(hours=3) if isinstance(start, datetime) else timedelta(days=1)))
    event.add("SUMMARY", f"{key[1]} @ {key[2]}")
    event.add("STATUS", "CONFIRMED")
    event.add("TRANSP", "TRANSPARENT")
    if game.get("location"):
        event.add("LOCATION", game["location"])
        event.add("X-GIANTS-CALENDAR-OFFICIAL-LOCATION", "true")
    return event


def scheduled_start(day: dict) -> datetime | None:
    value = day["game"].get("start")
    if not value:
        return None
    start = datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=JST)
    if start.date().isoformat() != day["date"]:
        raise ValueError(f"球団公式の試合開始日が不正です: {day['game']['id']}")
    return start if start.time() != time.min else None


def merge_games(
    games: dict, days: list[dict], matchup_key, previous: dict | None = None,
) -> tuple[dict, dict[str, str]]:
    result = dict(games)
    by_match = {key: uid for uid, event in result.items() if (key := matchup_key(event))}
    previous = previous or {}
    descriptions = {}
    seen = set()
    for day in days:
        if not day.get("game"):
            continue
        key = official_key(day)
        if key in seen:
            raise ValueError(f"球団公式の試合が重複しています: {key}")
        seen.add(key)
        game = day["game"]
        uid = by_match.get(key)
        if uid is None:
            if game.get("status") not in {"before", "after"}:
                print(f"球団公式の試合状態を確認できません: {game['id']} ({game.get('status')})", file=sys.stderr)
                continue
            event = new_game(day, key)
            uid = str(event["UID"])
            result[uid] = event
        previous_uid = previous.get(key)
        if previous_uid and previous_uid != uid:
            if previous_uid in result:
                raise ValueError(f"保存済み試合UIDが重複しています: {previous_uid}")
            event = copy.deepcopy(result.pop(uid))
            event["UID"] = previous_uid
            uid = previous_uid
            result[uid] = event
        event = copy.deepcopy(result[uid])
        start = event.decoded("DTSTART")
        scheduled = scheduled_start(day)
        if not isinstance(start, datetime) and scheduled is not None:
            event.pop("DTSTART", None)
            event.pop("DTEND", None)
            event.pop("DURATION", None)
            event.add("DTSTART", scheduled)
            event.add("DTEND", scheduled + timedelta(hours=3))
        if not event.get("LOCATION") and game.get("location"):
            event.add("LOCATION", game["location"])
            event.add("X-GIANTS-CALENDAR-OFFICIAL-LOCATION", "true")
        detail = detail_data(game["id"], day["date"])
        if detail is not None:
            official_start, end = detail["start"], detail["end"]
            start = event.decoded("DTSTART")
            if not isinstance(start, datetime):
                event.pop("DTSTART", None)
                event.add("DTSTART", official_start)
                start = official_start
            if start.tzinfo is None or end <= start:
                raise ValueError(f"試合終了時刻が開始時刻と整合しません: {game['id']}")
            event.pop("DTEND", None)
            event.pop("DURATION", None)
            event.add("DTEND", end)
            for side in ("home", "away"):
                starter = detail.get(f"{side}_starter")
                if starter:
                    event[f"X-GIANTS-CALENDAR-{side.upper()}-STARTER"] = starter.strip()
        scores = game.get("away_score"), game.get("home_score")
        if game.get("status") == "after" and all(type(score) is int and score >= 0 for score in scores):
            away, home = key[1:]
            event["SUMMARY"] = f"{away} ({scores[0]}) @ {home} ({scores[1]})"
        result[uid] = event
        descriptions[uid] = description(day)
    return result, descriptions


def add_calendar_details(
    calendar, days: list[dict], descriptions: dict[str, str],
) -> None:
    for event in calendar.walk("VEVENT"):
        text = descriptions.get(str(event.get("UID")), "")
        if text:
            previous = str(event.get("DESCRIPTION", "")).strip()
            event["DESCRIPTION"] = "\n\n".join(filter(None, (previous, text)))
    seen = set()
    for day in days:
        info = day.get("event")
        if not info:
            continue
        if not isinstance(info, dict) or not isinstance(info.get("title"), str) or not info["title"]:
            raise ValueError(f"球団公式イベントが不正です: {day['date']}")
        if day["date"] in seen:
            raise ValueError(f"同日の球団公式イベントが複数あります: {day['date']}")
        seen.add(day["date"])
        start = date.fromisoformat(day["date"])
        event = Event()
        event.add("UID", f"giants-official-event-{day['date']}@giants-calendar.local")
        event.add("DTSTAMP", datetime.combine(start, time.min, tzinfo=timezone.utc))
        event.add("DTSTART", start)
        event.add("DTEND", start + timedelta(days=1))
        event.add("SUMMARY", info["title"])
        if info.get("location"):
            event.add("LOCATION", info["location"])
        event.add("STATUS", "CONFIRMED")
        calendar.add_component(event)
