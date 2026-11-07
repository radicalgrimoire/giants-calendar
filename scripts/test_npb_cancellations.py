import json
import unittest
import urllib.error
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from icalendar import Event

import check_npb_cancellations as checker
import generate_calendar
import giants_official
import save_snapshot
from generate_calendar import JST


def event(uid: str, day: int, summary: str) -> Event:
    game = Event()
    game.add("UID", uid)
    game.add("DTSTART", datetime(2026, 7, day, 18, tzinfo=JST))
    game.add("SUMMARY", summary)
    return game


class CancellationTests(unittest.TestCase):
    def test_month_selection_including_new_year(self):
        self.assertEqual(checker.months_to_check(date(2026, 7, 6)), [(2026, 7)])
        self.assertEqual(checker.months_to_check(date(2026, 8, 1)), [(2026, 8), (2026, 7)])
        self.assertEqual(checker.months_to_check(date(2027, 1, 1)), [(2027, 1), (2026, 12)])

    def test_normalizes_explicit_cancellation_for_any_team(self):
        response = {
            "schema_version": 1,
            "games": [{"date": "2026-07-04", "home": "阪神", "away": "広島", "status": "中止"}],
        }
        with patch.object(checker, "request_gemini_json", return_value=response):
            games = checker.extract_cancellations("source", 2026, 7, "key")
        self.assertEqual(games, [{
            "date": "2026-07-04",
            "home": "阪神タイガース",
            "away": "広島東洋カープ",
            "status": "中止",
        }])

    def test_rejects_bad_ai_output(self):
        valid = {"date": "2026-07-04", "home": "阪神", "away": "広島", "status": "中止"}
        invalid = [
            {"schema_version": 1},
            {"schema_version": 1, "games": [dict(valid, status="延期")]},
            {"schema_version": 1, "games": [dict(valid, date="2026-08-04")]},
            {"schema_version": 1, "games": [dict(valid, date="2027-07-04")]},
            {"schema_version": 1, "games": [dict(valid, home="不明")]},
            {"schema_version": 1, "games": [dict(valid, away="阪神")]},
            {"schema_version": 1, "games": [valid, valid]},
        ]
        for response in invalid:
            with self.subTest(response=response), patch.object(checker, "request_gemini_json", return_value=response):
                with self.assertRaises(ValueError):
                    checker.extract_cancellations("source", 2026, 7, "key")

    def test_filters_only_matching_date_and_home_away(self):
        games = {
            "cancelled": event("cancelled", 4, "Yomiuri @ Hanshin"),
            "rescheduled": event("rescheduled", 5, "Yomiuri @ Hanshin"),
            "reverse": event("reverse", 4, "Hanshin @ Yomiuri"),
            "unknown": event("unknown", 4, "unknown event"),
        }
        cancellations = [{
            "date": "2026-07-04", "home": "阪神タイガース",
            "away": "読売ジャイアンツ", "status": "中止",
        }]
        self.assertEqual(
            set(generate_calendar.filter_games(games, cancellations)),
            {"rescheduled", "reverse", "unknown"},
        )

    def test_month_replacement_preserves_other_months_and_updates_calendar(self):
        july = {
            "date": "2026-07-04", "home": "阪神タイガース",
            "away": "読売ジャイアンツ", "status": "中止",
        }
        june = dict(july, date="2026-06-02")
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "cancellations-2026.json"
            path.write_text(json.dumps({"schema_version": 1, "games": [june, july]}), encoding="utf-8")
            with (
                patch.object(generate_calendar, "CANCELLATION_DIRECTORY", root),
                patch.object(checker, "fetch_schedule", return_value="source"),
                patch.object(checker, "extract_cancellations", return_value=[]),
            ):
                checker.update_cancellations(date(2026, 7, 6), "key")
                stored = generate_calendar.load_cancellations(2026)
            self.assertEqual(stored, [june])
            self.assertIn("game", generate_calendar.filter_games(
                {"game": event("game", 4, "Yomiuri @ Hanshin")}, stored
            ))

    def test_snapshot_to_cancellation_json_games_and_calendar(self):
        cancelled = event("cancelled", 4, "Yomiuri @ Hanshin")
        unplayed = event("unplayed", 5, "Yomiuri @ Hanshin")
        response = {
            "schema_version": 1,
            "games": [{"date": "2026-07-04", "home": "阪神", "away": "巨人", "status": "中止"}],
        }
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch.object(generate_calendar, "CANCELLATION_DIRECTORY", root),
                patch.object(generate_calendar, "SNAPSHOT_DIRECTORY", root),
                patch.object(generate_calendar, "GAMES_PATH", root / "games.json"),
                patch.object(giants_official, "DIRECTORY", root / "official"),
                patch.object(save_snapshot, "SNAPSHOT_DIRECTORY", root),
                patch.object(checker, "fetch_schedule", return_value="source"),
                patch.object(checker, "request_gemini_json", return_value=response),
            ):
                save_snapshot.save_snapshot([cancelled, unplayed])
                checker.update_cancellations(date(2026, 7, 6), "key")
                games, calendar = generate_calendar.generate_calendar(2026)
                generate_calendar.save_games(games)
                self.assertEqual(set(games), {"unplayed"})
                self.assertEqual(len(save_snapshot.load_snapshot(2026)), 2)
                output = [component for component in calendar.walk() if component.name == "VEVENT"]
                self.assertEqual([str(component["UID"]) for component in output], ["unplayed"])
                stored = json.loads((root / "games.json").read_text(encoding="utf-8"))
                self.assertEqual([record["uid"] for record in stored["events"]], ["unplayed"])

    def test_failure_does_not_save_partial_months(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch.object(generate_calendar, "CANCELLATION_DIRECTORY", root),
                patch.object(checker, "fetch_schedule", return_value="source"),
                patch.object(checker, "extract_cancellations", side_effect=[[], ValueError("invalid")]),
            ):
                with self.assertRaises(ValueError):
                    checker.update_cancellations(date(2026, 8, 1), "key")
            self.assertEqual(list(root.iterdir()), [])

    def test_offseason_missing_page_preserves_existing_data(self):
        error = urllib.error.HTTPError("url", 404, "not found", {}, None)
        with patch.object(checker.urllib.request, "urlopen", side_effect=error):
            self.assertIsNone(checker.fetch_schedule(2026, 12))
            with self.assertRaises(urllib.error.HTTPError):
                checker.fetch_schedule(2026, 7)

    def test_invalid_stored_cancellations_fail(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "cancellations-2026.json").write_text('{"schema_version": 1}', encoding="utf-8")
            with patch.object(generate_calendar, "CANCELLATION_DIRECTORY", root):
                with self.assertRaises(ValueError):
                    generate_calendar.load_cancellations(2026)


if __name__ == "__main__":
    unittest.main()
