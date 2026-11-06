import io
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from icalendar import Calendar, Event

from count_games_by_opponent import count_games, main
from japanese_holidays import parse_holidays

HOLIDAY_CSV = (
    "国民の祝日・休日月日,国民の祝日・休日名称\n"
    "2027/3/22,休日\n"
    "2027/5/7,祝日（テスト用）\n"
    "2027/7/19,海の日\n"
).encode("cp932")


def add_game(calendar, start, summary, status=None):
    event = Event()
    event.add("DTSTART", start)
    event.add("SUMMARY", summary)
    if status:
        event.add("STATUS", status)
    calendar.add_component(event)


class CountGamesByOpponentTests(unittest.TestCase):
    def test_counts_home_away_weekdays_and_weekends(self):
        calendar = Calendar()
        visitor = "東京ヤクルトスワローズ vs 読売ジャイアンツ 1回戦"
        home = "読売ジャイアンツ vs 東京ヤクルトスワローズ 2回戦"
        add_game(calendar, date(2027, 5, 7), visitor)
        add_game(calendar, date(2027, 5, 14), visitor)
        add_game(calendar, date(2027, 5, 6), visitor)
        add_game(calendar, date(2027, 5, 8), home)
        add_game(calendar, date(2027, 7, 19), visitor)
        add_game(calendar, date(2027, 5, 9), visitor, "CANCELLED")
        add_game(calendar, date(2026, 5, 9), visitor)
        add_game(calendar, date(2027, 6, 5), "千葉ロッテマリーンズ vs 読売ジャイアンツ 【交流戦】 1回戦")

        counts = count_games(calendar, parse_holidays(HOLIDAY_CSV, 2027))
        self.assertEqual(dict(counts["東京ヤクルトスワローズ"]), {"weekday": 2, "weekend": 3})
        self.assertEqual(dict(counts["千葉ロッテマリーンズ"]), {"weekend": 1})

    def test_utc_start_uses_japan_date(self):
        calendar = Calendar()
        add_game(calendar, datetime(2027, 5, 7, 16, tzinfo=timezone.utc),
                 "横浜DeNAベイスターズ vs 読売ジャイアンツ 1回戦")
        self.assertEqual(count_games(calendar, set())["横浜DeNAベイスターズ"]["weekend"], 1)

    def test_unrecognized_matchup_is_reported(self):
        calendar = Calendar()
        add_game(calendar, date(2027, 5, 8), "不明な対戦カード")
        add_game(calendar, date(2027, 5, 8), "ヤクルト vs DeNA 1回戦")
        errors = io.StringIO()
        with redirect_stderr(errors):
            self.assertEqual(count_games(calendar, set()), {})
        self.assertEqual(errors.getvalue().count("対戦相手を判定できません"), 2)

    def test_holiday_csv_includes_substitute_holidays(self):
        self.assertEqual(parse_holidays(HOLIDAY_CSV, 2027), {
            date(2027, 3, 22), date(2027, 5, 7), date(2027, 7, 19),
        })
        calendar = Calendar()
        add_game(calendar, date(2027, 3, 22), "横浜DeNAベイスターズ vs 読売ジャイアンツ 1回戦")
        self.assertEqual(count_games(calendar, parse_holidays(HOLIDAY_CSV, 2027))["横浜DeNAベイスターズ"]["weekend"], 1)

    def test_invalid_or_missing_holiday_data_fails(self):
        for contents in (b"bad header\n", "国民の祝日・休日月日,国民の祝日・休日名称\n2026/1/1,元日\n".encode("cp932"),
                         "国民の祝日・休日月日,国民の祝日・休日名称\n2027/13/1,不正\n".encode("cp932")):
            with self.subTest(contents=contents), self.assertRaises(ValueError):
                parse_holidays(contents, 2027)

    def test_output_format_and_totals(self):
        calendar = Calendar()
        add_game(calendar, date(2027, 5, 7), "東京ヤクルトスワローズ vs 読売ジャイアンツ 1回戦")
        add_game(calendar, date(2027, 5, 8), "読売ジャイアンツ vs 東京ヤクルトスワローズ 2回戦")
        add_game(calendar, date(2027, 6, 5), "オリックス・バファローズ vs 読売ジャイアンツ 1回戦")
        with TemporaryDirectory() as directory:
            path = Path(directory) / "games.ics"
            path.write_bytes(calendar.to_ical())
            holidays_path = Path(directory) / "holidays.csv"
            holidays_path.write_bytes(HOLIDAY_CSV)
            output = io.StringIO()
            with patch.object(sys, "argv", ["count_games_by_opponent.py", "--ics", str(path),
                                             "--holidays", str(holidays_path)]), redirect_stdout(output):
                main()
        self.assertEqual(output.getvalue(), (
            "2027年 ジャイアンツの対戦球団別試合数\n"
            "球団名（平日 / 週末＋祝日）\n\n"
            "オリックス・バファローズ（0試合 / 1試合）\n"
            "東京ヤクルトスワローズ（0試合 / 2試合）\n"
            "合計（0試合 / 3試合）\n"
        ))


if __name__ == "__main__":
    unittest.main()
