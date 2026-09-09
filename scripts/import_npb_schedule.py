#!/usr/bin/env python3
"""NPB日程ページから巨人戦を抽出してスナップショットへ補完する。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from icalendar import Event

from generate_calendar import (
    JST,
    write_json,
)
from save_snapshot import event_start, event_to_record, load_snapshot, snapshot_path


ROOT = Path(__file__).resolve().parents[1]
GIANTS = "読売ジャイアンツ"
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
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
            "表の左側のチームを away、右側を home とします。得点は各チームの横の数値です。",
            "日付、開始時刻、対戦チーム、得点のいずれかがページに明記されていない試合は除外してください。推測しないでください。",
            "同じ試合を重複して出力しないでください。",
            '{"schema_version":1,"games":[{"date":"2026-03-27","away":"巨人","home":"阪神","away_score":3,"home_score":1,"start_at":"18:15"}]}',
            f"対象年: {year}",
            "HTML:",
            source,
        )
    )
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
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                text = json.load(response)["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(text)
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            if error.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise RuntimeError(f"Gemini API 呼び出しに失敗しました: HTTP {error.code} {detail[:400]}") from error
            retry_after = error.headers.get("Retry-After")
            delay = int(retry_after) if retry_after and retry_after.isdigit() else 2**attempt
            print(f"Gemini API returned HTTP {error.code}; retrying in {delay} seconds.", file=sys.stderr)
            time.sleep(delay)
        except (urllib.error.URLError, TimeoutError, KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
            raise RuntimeError(f"Gemini の試合 JSON 生成に失敗しました: {error}") from error
    raise RuntimeError("Gemini API の再試行回数を超えました")


def validate_games(contents: object) -> list[dict[str, object]]:
    if not isinstance(contents, dict) or contents.get("schema_version") != 1:
        raise ValueError("試合 JSON の schema_version が不正です")
    records = contents.get("games")
    if not isinstance(records, list) or not records:
        raise ValueError("試合 JSON に games がありません")

    games: list[dict[str, object]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for index, record in enumerate(records, start=1):
        fields = ("date", "away", "home", "start_at")
        if not isinstance(record, dict) or any(not isinstance(record.get(field), str) for field in fields):
            raise ValueError(f"試合 JSON の games[{index}] が不正です")
        if not all(isinstance(record.get(field), int) and record[field] >= 0 for field in ("away_score", "home_score")):
            raise ValueError(f"試合 JSON の games[{index}] の得点が不正です")
        try:
            datetime.strptime(record["date"], "%Y-%m-%d")
            datetime.strptime(record["start_at"], "%H:%M")
            away_key, away_name = TEAM_ALIASES[record["away"].strip()]
            home_key, home_name = TEAM_ALIASES[record["home"].strip()]
        except (KeyError, ValueError) as error:
            raise ValueError(f"試合 JSON の games[{index}] の日付、時刻、またはチーム名が不正です") from error
        if GIANTS not in (away_name, home_name):
            raise ValueError(f"試合 JSON の games[{index}] は巨人戦ではありません")
        identity = (record["date"], away_key, home_key, record["start_at"])
        if identity in seen:
            raise ValueError(f"試合 JSON の games[{index}] が重複しています")
        seen.add(identity)
        games.append({
            "date": record["date"], "away": away_key, "home": home_key,
            "away_score": record["away_score"], "home_score": record["home_score"], "start_at": record["start_at"],
        })
    return games


def build_event(game: dict[str, object]) -> Event:
    start = datetime.strptime(f'{game["date"]} {game["start_at"]}', "%Y-%m-%d %H:%M").replace(tzinfo=JST)
    identity = f'{game["date"]}/{game["away"]}/{game["home"]}/{game["start_at"]}'
    uid = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    event = Event()
    event.add("UID", f"npb-{uid}@giants-calendar.local")
    event.add("DTSTAMP", datetime.now(timezone.utc))
    event.add("DTSTART", start)
    event.add("DTEND", start + timedelta(hours=3))
    event.add("SUMMARY", f'{game["away"]} ({game["away_score"]}) @ {game["home"]} ({game["home_score"]})')
    event.add("STATUS", "CONFIRMED")
    event.add("TRANSP", "TRANSPARENT")
    event.add("X-GIANTS-CALENDAR-SOURCE", "npb")
    return event


def save_snapshot_events(events: dict[str, Event], year: int) -> None:
    records = sorted((event_to_record(event) for event in events.values()), key=lambda record: (record["start"], record["uid"]))
    write_json(snapshot_path(year), {"schema_version": 1, "events": records})


def main() -> None:
    parser = argparse.ArgumentParser(description="NPB日程ページから巨人戦を取り込みます。")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--source", type=Path, help="取得済みHTMLファイル")
    source.add_argument("--games-json", type=Path, help="検証用のGemini出力JSON")
    parser.add_argument("--json-output", type=Path, help="Gemini出力JSONの保存先")
    args = parser.parse_args()

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
        contents = request_games(source_text, datetime.now(JST).year, api_key)
        write_json(args.json_output, contents)

    games = validate_games(contents)
    years = {datetime.strptime(str(game["date"]), "%Y-%m-%d").year for game in games}
    if len(years) != 1:
        raise ValueError("一度に取り込めるのは同一年の試合だけです")
    year = years.pop()
    snapshot = load_snapshot(year)
    imported = [build_event(game) for game in games]
    snapshot.update({str(event["UID"]): event for event in imported})
    save_snapshot_events(snapshot, year)
    print(f"Imported {len(imported)} games into {snapshot_path(year).relative_to(ROOT)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"NPB schedule import failed: {error}", file=sys.stderr)
        raise