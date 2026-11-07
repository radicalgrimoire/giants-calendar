import json
import unittest
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zoneinfo import ZoneInfo

from icalendar import Calendar

import generate_calendar
import giants_official
import save_snapshot
from import_npb_schedule import build_event


JST = ZoneInfo("Asia/Tokyo")


class GiantsOfficialTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.patcher = patch.object(giants_official, "DIRECTORY", self.root)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_existing_game_keeps_uid_result_and_adds_official_details(self):
        game = build_event({
            "date": "2027-03-26", "home": "Yomiuri", "away": "Chunichi",
            "start_at": "14:00",
        })
        uid = str(game["UID"])
        day = {
            "date": "2027-03-26",
            "game": {
                "id": "20270326_8003_1", "home": "巨人", "away": "中日",
                "status": "after", "home_score": 4, "away_score": 3,
                "location": "東京ドーム",
                "url": "https://www.giants.jp/game/20270326_8003_1/",
            },
            "events": [{"title": "イベント", "url": "https://example.com/"}],
        }
        (self.root / "detail-20270326_8003_1.json").write_text(json.dumps({
            "schema_version": 1, "date": "2027-03-26", "id": "20270326_8003_1",
            "start": "2027-03-26T14:00:00+09:00", "end": "2027-03-26T16:45:00+09:00",
        }), encoding="utf-8")
        games, descriptions = giants_official.merge_games({uid: game}, [day], generate_calendar.matchup_key)
        self.assertEqual(list(games), [uid])
        self.assertEqual(games[uid].decoded("DTEND"), datetime(2027, 3, 26, 16, 45, tzinfo=JST))
        calendar = generate_calendar.build_calendar(list(games.values()), 2027, {})
        giants_official.add_calendar_details(calendar, [day], descriptions)
        output = Calendar.from_ical(calendar.to_ical()).walk("VEVENT")[0]
        self.assertEqual(str(output["UID"]), uid)
        self.assertEqual(str(output["LOCATION"]), generate_calendar.HOME_STADIUMS["Yomiuri"])
        self.assertIn("（4 - 3）", str(output["SUMMARY"]))
        self.assertIn("試合結果：G4 - D3 勝利", str(output["DESCRIPTION"]))
        self.assertIn("https://www.giants.jp/game/20270326_8003_1/", str(output["DESCRIPTION"]))
        self.assertIn("・イベント\nhttps://example.com/", str(output["DESCRIPTION"]))

    def test_all_day_game_becomes_timed_when_details_arrive(self):
        game = build_event({"date": "2027-03-26", "home": "Yomiuri", "away": "Chunichi"})
        uid = str(game["UID"])
        day = {"date": "2027-03-26", "game": {"id": "20270326_8003_1", "home": "巨人", "away": "中日"}}
        (self.root / "detail-20270326_8003_1.json").write_text(json.dumps({
            "schema_version": 1, "date": "2027-03-26", "id": "20270326_8003_1",
            "start": "2027-03-26T14:00:00+09:00", "end": "2027-03-26T16:45:00+09:00",
        }), encoding="utf-8")
        games, _ = giants_official.merge_games({uid: game}, [day], generate_calendar.matchup_key)
        self.assertEqual(games[uid].decoded("DTSTART"), datetime(2027, 3, 26, 14, tzinfo=JST))
        self.assertEqual(games[uid].decoded("DTEND"), datetime(2027, 3, 26, 16, 45, tzinfo=JST))

    def test_camp_and_rest_are_stable_all_day_events(self):
        days = [
            {"date": "2026-11-01", "event": {"title": "秋季キャンプ", "location": "G球場",
             "url": "https://www.giants.jp/column/autumncamp2026/autumncamp2026/"}},
            {"date": "2026-11-02", "event": {"title": "休養日", "location": "", "url": None}},
        ]
        calendar = generate_calendar.build_calendar([], 2026, {})
        giants_official.add_calendar_details(calendar, days, {}, {
            "https://www.giants.jp/column/autumncamp2026/autumncamp2026/":
                "https://www.giants.jp/column/autumncamp2026/",
        })
        events = Calendar.from_ical(calendar.to_ical()).walk("VEVENT")
        self.assertEqual([e.decoded("DTSTART") for e in events], [date(2026, 11, 1), date(2026, 11, 2)])
        self.assertEqual(events[0].decoded("DTEND"), date(2026, 11, 2))
        self.assertEqual(str(events[0]["UID"]), "giants-official-event-2026-11-01@giants-calendar.local")
        self.assertEqual(str(events[0]["LOCATION"]), "G球場")
        self.assertEqual(str(events[0]["DESCRIPTION"]), "https://www.giants.jp/column/autumncamp2026/")
        self.assertEqual(days[0]["event"]["url"], "https://www.giants.jp/column/autumncamp2026/autumncamp2026/")
        self.assertEqual(str(events[1]["SUMMARY"]), "休養日")

    def test_game_and_campaign_urls_only_replace_exact_matches(self):
        source = "https://www.giants.jp/column/autumncamp2026/autumncamp2026/"
        other = "https://example.com/column/autumncamp2026/autumncamp2026/"
        game_url = "https://www.giants.jp/game/20261101_8003_1/"
        day = {"date": "2026-11-01", "game": {"url": game_url}, "events": [
            {"title": "秋季キャンプ", "url": source},
            {"title": "別のイベント", "url": other},
        ]}
        text = giants_official.description(day, {
            source: "https://www.giants.jp/column/autumncamp2026/",
            game_url: "https://example.com/game",
        })
        self.assertIn("試合詳細：\nhttps://example.com/game", text)
        self.assertIn("・秋季キャンプ\nhttps://www.giants.jp/column/autumncamp2026/", text)
        self.assertNotIn(source, text)
        self.assertIn(other, text)
        self.assertEqual(day["events"][0]["url"], source)

    def test_local_url_override_loading(self):
        path = self.root / "local-url.env"
        with patch.object(generate_calendar, "LOCAL_URL_PATH", path):
            self.assertEqual(generate_calendar.load_local_url_overrides(), {})
            path.write_text(
                "# URL overrides\n\nhttps://example.com/?key=1 = https://example.org/?value=2\n"
                "https://example.com/other = https://example.org/other\n",
                encoding="utf-8",
            )
            self.assertEqual(generate_calendar.load_local_url_overrides(), {
                "https://example.com/?key=1": "https://example.org/?value=2",
                "https://example.com/other": "https://example.org/other",
            })
            for content in (
                "https://example.com/=https://example.org/\n",
                "https://example.com/ = ftp://example.org/\n",
                "https://example.com/ = https://example.org:bad/\n",
                "https://example.com/ = https://example.org/\n"
                "https://example.com/ = https://example.net/\n",
            ):
                with self.subTest(content=content):
                    path.write_text(content, encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "local-url.env:"):
                        generate_calendar.load_local_url_overrides()

    def test_official_only_game_is_added_and_retains_uid_when_google_arrives(self):
        day = {"date": "2027-03-26", "game": {
            "id": "20270326_8003_1", "home": "巨人", "away": "中日",
            "start": "2027-3-26 14:00:00", "location": "東京ドーム", "status": "before",
        }}
        games, _ = giants_official.merge_games({}, [day], generate_calendar.matchup_key)
        uid = "giants-official-game-20270326_8003_1@giants-calendar.local"
        self.assertEqual(list(games), [uid])
        self.assertEqual(games[uid].decoded("DTSTART"), datetime(2027, 3, 26, 14, tzinfo=JST))
        google = build_event({"date": "2027-03-26", "home": "Yomiuri", "away": "Chunichi"})
        key = generate_calendar.matchup_key(google)
        merged, _ = giants_official.merge_games(
            {str(google["UID"]): google}, [day], generate_calendar.matchup_key, {key: uid}
        )
        self.assertEqual(list(merged), [uid])
        self.assertEqual(str(merged[uid]["UID"]), uid)

    def test_invalid_or_wrong_game_detail_fails(self):
        file = self.root / "detail-20270326_8003_1.json"
        file.write_text(json.dumps({
            "schema_version": 1, "date": "2027-03-26", "id": "different",
            "start": "2027-03-26T14:00:00+09:00", "end": "2027-03-26T16:45:00+09:00",
        }), encoding="utf-8")
        with self.assertRaises(ValueError):
            giants_official.detail_times("20270326_8003_1", "2027-03-26")

    def test_calendar_can_include_a_year_with_only_official_events(self):
        (self.root / "202811.json").write_text(json.dumps({
            "schema_version": 1, "month": "202811",
            "days": [{"date": "2028-11-01", "event": {"title": "秋季キャンプ"}}],
        }, ensure_ascii=False), encoding="utf-8")
        with (
            patch.object(generate_calendar, "SNAPSHOT_DIRECTORY", self.root / "games"),
            patch.object(generate_calendar, "CANCELLATION_DIRECTORY", self.root / "cancelled"),
            patch.object(generate_calendar, "GAMES_PATH", self.root / "games.json"),
            patch.object(generate_calendar, "LOCAL_STADIUM_PATH", self.root / "local.env"),
            patch.object(generate_calendar, "LOCAL_URL_PATH", self.root / "url.env"),
        ):
            _, calendar = generate_calendar.generate_all_calendars()
        events = calendar.walk("VEVENT")
        self.assertEqual(len(events), 1)
        self.assertEqual(str(events[0]["SUMMARY"]), "秋季キャンプ")

    def test_snapshot_to_final_calendar_preserves_uid_and_merges_details(self):
        baseline = self.root / "baseline"
        game = build_event({
            "date": "2027-03-26", "home": "Yomiuri", "away": "Chunichi",
            "start_at": "14:00",
        })
        uid = str(game["UID"])
        day = {
            "date": "2027-03-26",
            "game": {"id": "20270326_8003_1", "home": "巨人", "away": "中日",
                     "status": "after", "home_score": 4, "away_score": 3,
                     "url": "https://www.giants.jp/game/20270326_8003_1/"},
            "events": [{"title": "イベント", "url": "https://example.com/source"}],
        }
        (self.root / "url.env").write_text(
            "https://example.com/source = https://example.com/target\n",
            encoding="utf-8",
        )
        (self.root / "202703.json").write_text(json.dumps({
            "schema_version": 1, "month": "202703", "days": [day],
        }, ensure_ascii=False), encoding="utf-8")
        (self.root / "detail-20270326_8003_1.json").write_text(json.dumps({
            "schema_version": 1, "date": "2027-03-26", "id": "20270326_8003_1",
            "start": "2027-03-26T14:00:00+09:00", "end": "2027-03-26T16:45:00+09:00",
        }), encoding="utf-8")
        with (
            patch.object(save_snapshot, "SNAPSHOT_DIRECTORY", baseline),
            patch.object(generate_calendar, "SNAPSHOT_DIRECTORY", baseline),
            patch.object(generate_calendar, "CANCELLATION_DIRECTORY", self.root / "cancelled"),
            patch.object(generate_calendar, "GAMES_PATH", self.root / "games.json"),
            patch.object(generate_calendar, "LOCAL_STADIUM_PATH", self.root / "local.env"),
            patch.object(generate_calendar, "LOCAL_URL_PATH", self.root / "url.env"),
        ):
            save_snapshot.save_snapshot([game])
            _, calendar = generate_calendar.generate_calendar(2027)
        event = Calendar.from_ical(calendar.to_ical()).walk("VEVENT")[0]
        self.assertEqual(str(event["UID"]), uid)
        self.assertEqual(event.decoded("DTEND"), datetime(2027, 3, 26, 16, 45, tzinfo=JST))
        self.assertIn("試合結果：G4 - D3 勝利", str(event["DESCRIPTION"]))
        self.assertIn("・イベント", str(event["DESCRIPTION"]))
        self.assertIn("https://example.com/target", str(event["DESCRIPTION"]))
        self.assertEqual(day["events"][0]["url"], "https://example.com/source")


if __name__ == "__main__":
    unittest.main()
