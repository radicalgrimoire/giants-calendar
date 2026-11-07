import json
import sys
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from icalendar import Calendar

import generate_calendar as generator
import giants_official
import save_snapshot
from import_npb_schedule import build_event


def game(year: int, day: int = 26):
    return build_event({
        "date": f"{year}-03-{day:02d}", "home": "Yomiuri", "away": "Chunichi",
    })


class CalendarAggregationTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        patcher = patch.object(giants_official, "DIRECTORY", Path(directory.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_multi_year_selection_and_yearly_archive(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            snapshots = root / "snapshots"
            cancellations = root / "cancellations"
            output = root / "giants.ics"
            games_path = root / "games.json"
            archive = root / "giants-2026.ics"
            archive.write_text("old archive", encoding="utf-8")
            with (
                patch.object(save_snapshot, "SNAPSHOT_DIRECTORY", snapshots),
                patch.object(generator, "SNAPSHOT_DIRECTORY", snapshots),
                patch.object(generator, "CANCELLATION_DIRECTORY", cancellations),
                patch.object(generator, "OUTPUT_PATH", output),
                patch.object(generator, "GAMES_PATH", games_path),
                patch.object(generator, "ROOT", root),
                patch.object(generator, "LOCAL_STADIUM_PATH", root / "local.env"),
            ):
                save_snapshot.save_snapshot([game(2026), game(2027), game(2027, 27)])
                generator.write_json(cancellations / "cancellations-2027.json", {
                    "schema_version": 1,
                    "games": [{
                        "date": "2027-03-27", "home": "読売ジャイアンツ",
                        "away": "中日ドラゴンズ", "status": "中止",
                    }],
                })
                with patch.object(sys, "argv", ["generate_calendar.py"]):
                    generator.main()
                records = json.loads(games_path.read_text(encoding="utf-8"))["events"]
                result = Calendar.from_ical(output.read_bytes())
                events = result.walk("VEVENT")
                self.assertEqual(len(records), 2)
                self.assertEqual(len(events), 2)
                self.assertEqual(len(result.walk("VTIMEZONE")), 1)
                self.assertEqual(
                    [event.decoded("DTSTART") for event in events],
                    [date(2026, 3, 26), date(2027, 3, 26)],
                )
                self.assertTrue(all("1回戦" in str(event["SUMMARY"]) for event in events))
                output_before = output.read_bytes()
                games_before = games_path.read_bytes()
                with patch.object(sys, "argv", [
                    "generate_calendar.py", "--year", "2026", "--output", str(archive)
                ]):
                    generator.main()
                archived = Calendar.from_ical(archive.read_bytes()).walk("VEVENT")
                self.assertEqual([e.decoded("DTSTART") for e in archived], [date(2026, 3, 26)])
                self.assertEqual(output.read_bytes(), output_before)
                self.assertEqual(games_path.read_bytes(), games_before)
                save_snapshot.save_snapshot([game(2028)])
                with patch.object(sys, "argv", ["generate_calendar.py"]):
                    generator.main()
                updated = Calendar.from_ical(output.read_bytes()).walk("VEVENT")
                self.assertEqual(
                    [event.decoded("DTSTART").year for event in updated],
                    [2026, 2027, 2028],
                )
                self.assertEqual(len(json.loads(games_path.read_text(encoding="utf-8"))["events"]), 3)

    def test_duplicate_uids_across_years_fail(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            first, second = game(2026), game(2027)
            second["UID"] = first["UID"]
            with (
                patch.object(save_snapshot, "SNAPSHOT_DIRECTORY", root),
                patch.object(generator, "SNAPSHOT_DIRECTORY", root),
                patch.object(generator, "CANCELLATION_DIRECTORY", root),
            ):
                save_snapshot.save_snapshot([first, second])
                with self.assertRaisesRegex(ValueError, "UID"):
                    generator.generate_all_calendars()

    def test_no_snapshots_fails(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(generator, "SNAPSHOT_DIRECTORY", root):
                with self.assertRaises(FileNotFoundError):
                    generator.generate_all_calendars()

    def test_single_year_needs_no_year_setting(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch.object(save_snapshot, "SNAPSHOT_DIRECTORY", root),
                patch.object(generator, "SNAPSHOT_DIRECTORY", root),
                patch.object(generator, "CANCELLATION_DIRECTORY", root),
            ):
                save_snapshot.save_snapshot([game(2026)])
                games, calendar = generator.generate_all_calendars()
                self.assertEqual(len(games), 1)
                self.assertEqual(len(calendar.walk("VEVENT")), 1)

    def test_wrong_year_in_snapshot_fails(self):
        with patch.object(generator, "load_snapshot", return_value={"wrong": game(2026)}):
            with patch.object(generator, "load_cancellations", return_value=[]):
                with self.assertRaisesRegex(ValueError, "別の年"):
                    generator.generate_calendar(2027)

    def test_yearly_output_cannot_replace_combined_calendar(self):
        with patch.object(sys, "argv", ["generate_calendar.py", "--year", "2026"]):
            with self.assertRaises(SystemExit):
                generator.main()
        with patch.object(sys, "argv", [
            "generate_calendar.py", "--year", "2026", "--output", str(generator.OUTPUT_PATH)
        ]):
            with self.assertRaises(SystemExit):
                generator.main()

if __name__ == "__main__":
    unittest.main()
