"""Tests for the 2027 weekend away game selection."""

import io
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from icalendar import Calendar, Event

from weekend_away_games import JST, main, select_games


def add_game(calendar, start, summary, location, status=None):
    event = Event()
    event.add("DTSTART", start)
    event.add("SUMMARY", summary)
    if location is not None:
        event.add("LOCATION", location)
    if status:
        event.add("STATUS", status)
    calendar.add_component(event)


class WeekendAwayGamesTests(unittest.TestCase):
    def test_selects_kanto_away_games_on_all_days(self):
        calendar = Calendar()
        visitor = "東京ヤクルトスワローズ vs 読売ジャイアンツ 7回戦"
        add_game(calendar, date(2027, 5, 8), visitor, "明治神宮野球場, 東京都新宿区")
        add_game(calendar, datetime(2027, 5, 9, 14, tzinfo=JST), visitor, "横浜スタジアム, 神奈川県横浜市")
        add_game(calendar, date(2027, 5, 7), visitor, "明治神宮野球場, 東京都新宿区")
        add_game(calendar, date(2027, 5, 6), visitor, "明治神宮野球場, 東京都新宿区")
        add_game(calendar, date(2026, 5, 9), visitor, "明治神宮野球場, 東京都新宿区")
        add_game(calendar, date(2027, 5, 8), visitor, "東京ドーム, 東京都文京区")
        add_game(calendar, date(2027, 5, 8), visitor, "甲子園球場, 兵庫県西宮市")
        add_game(calendar, date(2027, 5, 8), visitor, "明治神宮野球場, 東京都新宿区", "CANCELLED")
        add_game(calendar, date(2027, 5, 8), "読売ジャイアンツ vs 東京ヤクルトスワローズ 1回戦", "明治神宮野球場, 東京都新宿区")

        games = select_games(calendar)
        self.assertEqual(games, [
            (date(2027, 5, 6), "東京ヤクルトスワローズ"),
            (date(2027, 5, 7), "東京ヤクルトスワローズ"),
            (date(2027, 5, 8), "東京ヤクルトスワローズ"),
            (date(2027, 5, 9), "東京ヤクルトスワローズ"),
        ])

    def test_utc_start_is_converted_before_checking_weekend(self):
        calendar = Calendar()
        add_game(calendar, datetime(2027, 5, 6, 16, tzinfo=timezone.utc),
                 "横浜DeNAベイスターズ vs 読売ジャイアンツ 1回戦", "横浜スタジアム, 神奈川県横浜市")
        games = select_games(calendar)
        self.assertEqual(games, [(date(2027, 5, 7), "横浜DeNAベイスターズ")])

    def test_unclassifiable_games_are_reported(self):
        calendar = Calendar()
        add_game(calendar, date(2027, 5, 8), "不明な対戦カード", "東京都")
        add_game(calendar, date(2027, 5, 8), "ヤクルト vs 読売ジャイアンツ 1回戦", None)
        errors = io.StringIO()
        with redirect_stderr(errors):
            self.assertEqual(select_games(calendar), [])
        self.assertIn("対戦カードを判定できません", errors.getvalue())
        self.assertIn("都道府県を判定できません", errors.getvalue())

    def test_interleague_and_cs_titles(self):
        calendar = Calendar()
        add_game(calendar, date(2027, 6, 5), "千葉ロッテマリーンズ vs 読売ジャイアンツ 【交流戦】 1回戦",
                 "ZOZOマリンスタジアム, 千葉県千葉市")
        add_game(calendar, date(2027, 10, 9), "【CS】横浜DeNAベイスターズ vs 読売ジャイアンツ 第1戦",
                 "横浜スタジアム, 神奈川県横浜市")
        self.assertEqual(len(select_games(calendar)), 2)

    def test_monday_games_are_included(self):
        calendar = Calendar()
        visitor = "東京ヤクルトスワローズ vs 読売ジャイアンツ 17回戦"
        add_game(calendar, date(2027, 7, 19), visitor, "明治神宮野球場, 東京都新宿区")
        add_game(calendar, date(2027, 7, 12), visitor, "明治神宮野球場, 東京都新宿区")
        add_game(calendar, date(2027, 7, 19), visitor, "甲子園球場, 兵庫県西宮市")
        add_game(calendar, date(2027, 7, 19), visitor, "明治神宮野球場, 東京都新宿区", "CANCELLED")
        self.assertEqual(select_games(calendar), [
            (date(2027, 7, 12), "東京ヤクルトスワローズ"),
            (date(2027, 7, 19), "東京ヤクルトスワローズ"),
        ])

    def test_output_format(self):
        calendar = Calendar()
        add_game(calendar, date(2027, 5, 7), "東京ヤクルトスワローズ vs 読売ジャイアンツ 6回戦",
                 "明治神宮野球場, 東京都新宿区")
        add_game(calendar, date(2027, 5, 6), "東京ヤクルトスワローズ vs 読売ジャイアンツ 5回戦",
                 "明治神宮野球場, 東京都新宿区")
        add_game(calendar, date(2027, 5, 8), "東京ヤクルトスワローズ vs 読売ジャイアンツ 7回戦",
                 "明治神宮野球場, 東京都新宿区")
        add_game(calendar, date(2027, 7, 19), "東京ヤクルトスワローズ vs 読売ジャイアンツ 17回戦",
                 "明治神宮野球場, 東京都新宿区")
        with TemporaryDirectory() as directory:
            path = Path(directory) / "games.ics"
            path.write_bytes(calendar.to_ical())
            holidays_path = Path(directory) / "holidays.csv"
            holidays_path.write_bytes((
                "国民の祝日・休日月日,国民の祝日・休日名称\n2027/7/19,海の日\n"
            ).encode("cp932"))
            output = io.StringIO()
            with patch.object(sys, "argv", ["weekend_away_games.py", "--ics", str(path),
                                             "--holidays", str(holidays_path)]), redirect_stdout(output):
                main()
        self.assertEqual(output.getvalue(), (
            "【平日】\n2027-05-06（木） vs 東京ヤクルトスワローズ\n"
            "2027-05-07（金） vs 東京ヤクルトスワローズ\n\n"
            "【土日祝日】\n2027-05-08（土） vs 東京ヤクルトスワローズ\n"
            "2027-07-19（月） vs 東京ヤクルトスワローズ\n"
        ))


if __name__ == "__main__":
    unittest.main()
