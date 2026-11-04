#!/usr/bin/env python3
"""NPB日程ページから巨人戦を抽出してスナップショットへ補完する。"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

from icalendar import Event

from generate_calendar import (
    JST,
    TEAM_NAMES,
    has_score,
    matchup_key,
    write_json,
)
from save_snapshot import (
    event_to_record,
    load_snapshot,
    snapshot_path,
)


ROOT = Path(__file__).resolve().parents[1]
GIANTS = "読売ジャイアンツ"
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
GEMINI_REQUEST_ATTEMPTS = 6
SOURCE_YEAR_PATTERN = re.compile(r"/games/(\d{4})/schedule_(\d{2})_detail\.html")
TEAM_ALIASES = {
    "巨人": ("Yomiuri", GIANTS),
    "読売": ("Yomiuri", GIANTS),
    "読売ジャイアンツ": ("Yomiuri", GIANTS),
    "阪神": ("Hanshin", "阪神タイガース"),
    "阪神タイガース": ("Hanshin", "阪神タイガース"),
    "広島": ("Hiroshima", "広島東洋カープ"),
    "広島東洋カープ": ("Hiroshima", "広島東洋カープ"),
    "中日": ("Chunichi", "中日ドラゴンズ"),
    "中日ドラゴンズ": ("Chunichi", "中日ドラゴンズ"),
    "DeNA": ("DeNA", "横浜DeNAベイスターズ"),
    "横浜DeNAベイスターズ": ("DeNA", "横浜DeNAベイスターズ"),
    "ヤクルト": ("Yakult", "東京ヤクルトスワローズ"),
    "東京ヤクルトスワローズ": ("Yakult", "東京ヤクルトスワローズ"),
    "ソフトバンク": ("SoftBank", "福岡ソフトバンクホークス"),
    "福岡ソフトバンクホークス": ("SoftBank", "福岡ソフトバンクホークス"),
    "日本ハム": ("Nippon-Ham", "北海道日本ハムファイターズ"),
    "北海道日本ハムファイターズ": ("Nippon-Ham", "北海道日本ハムファイターズ"),
    "ロッテ": ("Lotte", "千葉ロッテマリーンズ"),
    "千葉ロッテマリーンズ": ("Lotte", "千葉ロッテマリーンズ"),
    "楽天": ("Rakuten", "東北楽天ゴールデンイーグルス"),
    "東北楽天ゴールデンイーグルス": ("Rakuten", "東北楽天ゴールデンイーグルス"),
    "オリックス": ("Orix", "オリックス・バファローズ"),
    "オリックス・バファローズ": ("Orix", "オリックス・バファローズ"),
    "西武": ("Seibu", "埼玉西武ライオンズ"),
    "埼玉西武ライオンズ": ("Seibu", "埼玉西武ライオンズ"),
}


def request_games(source: str, year: int, api_key: str) -> dict:
    prompt = "\n".join(
        (
            "あなたはNPB公式戦の日程詳細HTMLを構造化するアシスタントです。",
            "読売ジャイアンツ（巨人・読売を含む）の試合だけを漏れなく抽出し、JSONだけを返してください。",
            "表の左側のチームを home、右側を away とします。得点は各チームの横の数値です。",
            "日付と対戦チームが明記された試合を抽出してください。球場、開始時刻、得点が未掲載の場合は、そのフィールドを省略してください。推測しないでください。",
            "「予備日」と表示された日程は、対戦チームが明記されていても試合に含めないでください。",
            "同じ試合を重複して出力しないでください。",
            '{"schema_version":1,"games":[{"date":"2027-03-26","home":"巨人","away":"中日","place":"東京ドーム"}]}',
            f"対象年: {year}",
            "HTML:",
            source,
        )
    )
    return request_gemini_json(prompt, api_key)


def request_gemini_json(prompt: str, api_key: str) -> dict:
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
    }
    request = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-goog-api-key": api_key},
        method="POST",
    )
    for attempt in range(GEMINI_REQUEST_ATTEMPTS):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                text = json.load(response)["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(text)
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            if (
                error.code not in (429, 500, 502, 503, 504)
                or attempt == GEMINI_REQUEST_ATTEMPTS - 1
            ):
                raise RuntimeError(f"Gemini API 呼び出しに失敗しました: HTTP {error.code} {detail[:400]}") from error
            retry_after = error.headers.get("Retry-After")
            delay = (
                float(retry_after)
                if retry_after and retry_after.replace(".", "", 1).isdigit()
                else 2**attempt
            )
            delay += random.uniform(0, 1)
            print(
                f"Gemini API returned HTTP {error.code}; retrying in {delay:.1f} seconds.",
                file=sys.stderr,
            )
            time.sleep(delay)
        except (urllib.error.URLError, TimeoutError, KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
            raise RuntimeError(f"Gemini の試合 JSON 生成に失敗しました: {error}") from error
    raise RuntimeError("Gemini API の再試行回数を超えました")


def source_year(source: str) -> int:
    match = SOURCE_YEAR_PATTERN.search(source)
    if not match:
        raise ValueError("NPB HTMLから対象年を取得できません")
    return int(match.group(1))


class ReserveDateParser(HTMLParser):
    def __init__(self, year: int, month: int) -> None:
        super().__init__()
        self.year = year
        self.month = month
        self.depth = 0
        self.in_schedule = False
        self.found_schedule = False
        self.row: dict[str, str] | None = None
        self.capture: str | None = None
        self.capture_depth = 0
        self.regular: set[tuple[str, str, str]] = set()
        self.reserves: set[tuple[str, str, str]] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "div":
            if not self.in_schedule and attributes.get("id") == "schedule_detail":
                self.in_schedule = True
                self.found_schedule = True
                self.depth = 1
            elif self.in_schedule:
                self.depth += 1
            if self.row is not None and self.capture is None:
                classes = (attributes.get("class") or "").split()
                for field in ("team1", "team2", "cancel", "state"):
                    if field in classes:
                        self.capture = field
                        self.capture_depth = self.depth
                        break
        elif tag == "tr" and self.in_schedule:
            self.row = {
                "id": attributes.get("id") or "",
                "team1": "",
                "team2": "",
                "cancel": "",
                "state": "",
            }

    def handle_data(self, data: str) -> None:
        if self.row is not None and self.capture is not None:
            self.row[self.capture] += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "tr" and self.row is not None:
            row = self.row
            self.row = None
            home, away = row["team1"].strip(), row["team2"].strip()
            if "巨人" not in (home, away) and "読売" not in (home, away) and GIANTS not in (home, away):
                return
            try:
                date_match = re.fullmatch(r"date(\d{2})(\d{2})", row["id"])
                if date_match is None:
                    raise ValueError("日付がありません")
                month, day = map(int, date_match.groups())
                if month != self.month:
                    raise ValueError("ページと試合の月が一致しません")
                game_date = datetime(self.year, month, day).date().isoformat()
                home_key = TEAM_ALIASES[home][0]
                away_key = TEAM_ALIASES[away][0]
            except (KeyError, ValueError) as error:
                raise ValueError("NPB HTMLの巨人戦の日付またはチームを解析できません") from error
            key = (game_date, away_key, home_key)
            (self.reserves if "予備日" in row["cancel"] + row["state"] else self.regular).add(key)
        elif tag == "div" and self.in_schedule:
            if self.capture is not None and self.capture_depth == self.depth:
                self.capture = None
            self.depth -= 1
            if self.depth == 0:
                self.in_schedule = False


def reserve_matchups(source: str) -> set[tuple[str, str, str]]:
    match = SOURCE_YEAR_PATTERN.search(source)
    if not match:
        raise ValueError("NPB HTMLから対象年と月を取得できません")
    parser = ReserveDateParser(int(match.group(1)), int(match.group(2)))
    parser.feed(source)
    parser.close()
    if not parser.found_schedule:
        raise ValueError("NPB HTMLに日程詳細がありません")
    return parser.reserves - parser.regular


def validate_games(
    contents: object, *, allow_empty: bool = False
) -> list[dict[str, object]]:
    if not isinstance(contents, dict) or contents.get("schema_version") != 1:
        raise ValueError("試合 JSON の schema_version が不正です")
    records = contents.get("games")
    if not isinstance(records, list) or (not records and not allow_empty):
        raise ValueError("試合 JSON に games がありません")

    games: list[dict[str, object]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for index, record in enumerate(records, start=1):
        fields = ("date", "away", "home")
        if not isinstance(record, dict) or any(not isinstance(record.get(field), str) for field in fields):
            raise ValueError(f"試合 JSON の games[{index}] が不正です")
        is_reserve = record.get("is_reserve", False)
        if not isinstance(is_reserve, bool):
            raise ValueError(f"試合 JSON の games[{index}] の予備日フラグが不正です")
        start_at = record.get("start_at")
        if start_at is not None and not isinstance(start_at, str):
            raise ValueError(f"試合 JSON の games[{index}] の開始時刻が不正です")
        place = record.get("place")
        if place is not None and not isinstance(place, str):
            raise ValueError(f"試合 JSON の games[{index}] の球場が不正です")
        scores = (record.get("away_score"), record.get("home_score"))
        if (scores[0] is None) != (scores[1] is None) or any(
            score is not None and (not isinstance(score, int) or score < 0)
            for score in scores
        ):
            raise ValueError(f"試合 JSON の games[{index}] の得点が不正です")
        try:
            datetime.strptime(record["date"], "%Y-%m-%d")
            if start_at is not None:
                datetime.strptime(start_at, "%H:%M")
            away_key, away_name = TEAM_ALIASES[record["away"].strip()]
            home_key, home_name = TEAM_ALIASES[record["home"].strip()]
        except (KeyError, ValueError) as error:
            raise ValueError(f"試合 JSON の games[{index}] の日付、時刻、またはチーム名が不正です") from error
        if GIANTS not in (away_name, home_name):
            raise ValueError(f"試合 JSON の games[{index}] は巨人戦ではありません")
        if is_reserve:
            print(f"Excluded reserve date: {record['date']} {away_key} @ {home_key}")
            continue
        identity = (record["date"], away_key, home_key, start_at or "")
        if identity in seen:
            raise ValueError(f"試合 JSON の games[{index}] が重複しています")
        seen.add(identity)
        game: dict[str, object] = {
            "date": record["date"], "away": away_key, "home": home_key,
        }
        if start_at is not None:
            game["start_at"] = start_at
        if place is not None:
            game["place"] = place.strip()
        if scores[0] is not None:
            game["away_score"], game["home_score"] = scores
        games.append(game)
    return games


def games_for_json(games: list[dict[str, object]]) -> dict[str, object]:
    records = []
    for game in games:
        record = {
            "date": game["date"],
            "away": TEAM_NAMES[str(game["away"])],
            "home": TEAM_NAMES[str(game["home"])],
        }
        for field in ("away_score", "home_score", "start_at", "place"):
            if field in game:
                record[field] = game[field]
        records.append(record)
    return {"schema_version": 1, "games": records}


def build_event(game: dict[str, object]) -> Event:
    game_date = datetime.strptime(str(game["date"]), "%Y-%m-%d").date()
    start_at = game.get("start_at")
    if start_at is None:
        start = game_date
        end = game_date + timedelta(days=1)
        time_identity = "all-day"
    else:
        start = datetime.strptime(
            f'{game["date"]} {start_at}', "%Y-%m-%d %H:%M"
        ).replace(tzinfo=JST)
        end = start + timedelta(hours=3)
        time_identity = str(start_at)
    identity = f'{game["date"]}/{game["away"]}/{game["home"]}/{time_identity}'
    uid = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    event = Event()
    event.add("UID", f"npb-{uid}@giants-calendar.local")
    event.add("DTSTAMP", datetime.now(timezone.utc))
    event.add("DTSTART", start)
    event.add("DTEND", end)
    if place := game.get("place"):
        event.add("LOCATION", place)
    away_score = game.get("away_score")
    home_score = game.get("home_score")
    summary = f'{game["away"]} @ {game["home"]}'
    if away_score is not None and home_score is not None:
        summary = f'{game["away"]} ({away_score}) @ {game["home"]} ({home_score})'
    event.add("SUMMARY", summary)
    event.add("STATUS", "CONFIRMED")
    event.add("TRANSP", "TRANSPARENT")
    event.add("X-GIANTS-CALENDAR-SOURCE", "npb")
    return event


def save_snapshot_events(events: dict[str, Event], year: int) -> None:
    records = sorted((event_to_record(event) for event in events.values()), key=lambda record: (record["start"], record["uid"]))
    write_json(snapshot_path(year), {"schema_version": 1, "events": records})


def merge_npb_events(snapshot: dict[str, Event], imported: list[Event]) -> dict[str, Event]:
    result = dict(snapshot)
    previous_by_key = {
        key: event
        for event in snapshot.values()
        if str(event.get("X-GIANTS-CALENDAR-SOURCE", "")) == "npb"
        if (key := matchup_key(event)) is not None
    }
    for event in imported:
        previous = previous_by_key.get(matchup_key(event))
        if previous is not None:
            event = copy.deepcopy(event)
            if not isinstance(event.decoded("DTSTART"), datetime) and isinstance(
                previous.decoded("DTSTART"), datetime
            ):
                for field in ("DTSTART", "DTEND", "DURATION"):
                    event.pop(field, None)
                    if field in previous:
                        event[field] = copy.deepcopy(previous[field])
            if not has_score(event) and has_score(previous):
                event["SUMMARY"] = copy.deepcopy(previous["SUMMARY"])
            event["UID"] = copy.deepcopy(previous["UID"])
            event.add("SEQUENCE", int(previous.get("SEQUENCE", 0)) + 1)
        result[str(event["UID"])] = event
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="NPB日程ページから巨人戦を取り込みます。")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--source", type=Path, help="取得済みHTMLファイル")
    source.add_argument("--games-json", type=Path, help="検証用のGemini出力JSON")
    parser.add_argument("--json-output", type=Path, help="Gemini出力JSONの保存先")
    args = parser.parse_args()

    reserve_keys: set[tuple[str, str, str]] = set()
    if args.games_json:
        contents = json.loads(args.games_json.read_text(encoding="utf-8"))
    else:
        api_key = os.environ.get("GEMINI_APIKEY", "").strip()
        if not api_key:
            parser.error("GEMINI_APIKEY が未設定です。")
        if args.json_output is None:
            parser.error("--source の場合は --json-output が必要です。")
        source_text = args.source.read_text(encoding="utf-8")
        if not source_text.strip():
            parser.error("HTMLが空です。")
        year = source_year(source_text)
        reserve_keys = reserve_matchups(source_text)
        contents = request_games(source_text, year, api_key)

    games = validate_games(contents, allow_empty=True)
    before_filter = len(games)
    games = [
        game
        for game in games
        if (str(game["date"]), str(game["away"]), str(game["home"])) not in reserve_keys
    ]
    if before_filter != len(games):
        print(f"Excluded {before_filter - len(games)} reserve dates from NPB output.")
    years = {datetime.strptime(str(game["date"]), "%Y-%m-%d").year for game in games}
    if len(years) > 1:
        raise ValueError("一度に取り込めるのは同一年の試合だけです")
    if not years and args.games_json:
        print("No non-reserve games to import.")
        return
    year = years.pop() if years else source_year(source_text)
    if not args.games_json and year != source_year(source_text):
        raise ValueError("試合 JSON の年度がNPBページの年度と一致しません")
    if not args.games_json:
        write_json(args.json_output, games_for_json(games))
    snapshot = load_snapshot(year)
    previous_count = len(snapshot)
    reserve_event_keys = {
        (game_date, TEAM_NAMES[away], TEAM_NAMES[home])
        for game_date, away, home in reserve_keys
    }
    snapshot = {
        uid: event
        for uid, event in snapshot.items()
        if not (
            str(event.get("X-GIANTS-CALENDAR-SOURCE", "")) == "npb"
            and matchup_key(event) in reserve_event_keys
            and not has_score(event)
        )
    }
    if len(snapshot) != previous_count:
        print(f"Removed {previous_count - len(snapshot)} reserve dates from the NPB snapshot.")
    imported = [build_event(game) for game in games]
    snapshot = merge_npb_events(snapshot, imported)
    save_snapshot_events(snapshot, year)
    print(f"Imported {len(imported)} games into {snapshot_path(year).relative_to(ROOT)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"NPB schedule import failed: {error}", file=sys.stderr)
        raise