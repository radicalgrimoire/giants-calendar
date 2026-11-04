import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from icalendar import Event

import check_duplicate_game_dates as checker
from generate_calendar import event_to_record


def record(uid: str, start: date | datetime) -> dict[str, str]:
    event = Event()
    event.add("UID", uid)
    event.add("DTSTAMP", datetime(2026, 1, 1, tzinfo=timezone.utc))
    event.add("DTSTART", start)
    event.add("DTEND", start + (timedelta(hours=3) if isinstance(start, datetime) else timedelta(days=1)))
    event.add("SUMMARY", uid)
    return event_to_record(event)


class DuplicateGameDatesTests(unittest.TestCase):
    def test_duplicates_use_jst_and_report_all_day(self):
        games = [
            record("all-day", date(2027, 3, 26)),
            record("timed", datetime(2027, 3, 26, 9, tzinfo=timezone.utc)),
            record("next-day", datetime(2027, 3, 26, 16, tzinfo=timezone.utc)),
        ]
        with TemporaryDirectory() as directory:
            path = Path(directory) / "games.json"
            path.write_text(json.dumps({"schema_version": 1, "events": games}), encoding="utf-8")
            output = StringIO()
            with patch.object(checker, "GAMES_PATH", path), redirect_stderr(output):
                with self.assertRaises(SystemExit) as error:
                    checker.main()
            self.assertEqual(error.exception.code, 1)
            self.assertIn("2027-03-26", output.getvalue())
            self.assertIn("終日 all-day (UID: all-day)", output.getvalue())
            self.assertIn("18:00 timed (UID: timed)", output.getvalue())
            self.assertNotIn("next-day", output.getvalue())

    def test_distinct_days_pass(self):
        games = [
            record("first", date(2027, 3, 26)),
            record("second", date(2027, 3, 27)),
        ]
        with TemporaryDirectory() as directory:
            path = Path(directory) / "games.json"
            path.write_text(json.dumps({"schema_version": 1, "events": games}), encoding="utf-8")
            output = StringIO()
            with patch.object(checker, "GAMES_PATH", path), redirect_stdout(output):
                checker.main()
            self.assertIn("同一日に複数の試合はありません", output.getvalue())

    def test_invalid_input_fails(self):
        cases = [
            {"schema_version": 2, "events": []},
            {"schema_version": 1, "events": "bad"},
            {"schema_version": 1, "events": [{"uid": "a", "start": "2027-03-26", "ical": "x"}]},
            {"schema_version": 1, "events": [{"uid": "a", "start": "bad", "ical": "x"}]},
            {"schema_version": 1, "events": [{"uid": "", "start": "2027-03-26T00:00:00+00:00", "ical": "x"}]},
        ]
        with TemporaryDirectory() as directory:
            path = Path(directory) / "games.json"
            for contents in cases:
                with self.subTest(contents=contents):
                    path.write_text(json.dumps(contents), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        checker.load_games(path)


if __name__ == "__main__":
    unittest.main()
