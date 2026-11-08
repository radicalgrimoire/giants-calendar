import json
import sys
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from icalendar import Event

import import_npb_schedule
import save_snapshot
from import_npb_schedule import build_event, reserve_matchups, validate_games


SEPTEMBER_HTML = """
<link rel="canonical" href="https://npb.jp/games/2027/schedule_09_detail.html">
<div id="schedule_detail"><table>
<tr id="date0910"><td><div class="team1">広島</div>
<div class="cancel">(予備日)</div><div class="team2">巨人</div></td></tr>
<tr id="date0926"><td><div class="team1">ヤクルト</div>
<div class="cancel">(予備日)</div><div class="team2">巨人</div></td></tr>
<tr id="date0911"><td><div class="team1">広島</div>
<div class="state">-</div><div class="team2">巨人</div></td></tr>
</table></div>
"""


def september_source(root: Path) -> Path:
    source = root / "schedule_09_detail.html"
    source.write_text(SEPTEMBER_HTML, encoding="utf-8")
    return source


def google_event(uid: str, summary: str) -> Event:
    event = Event()
    event.add("UID", uid)
    event.add("DTSTAMP", datetime(2026, 11, 1, tzinfo=timezone.utc))
    event.add("DTSTART", datetime(2027, 9, 10, 9, tzinfo=timezone.utc))
    event.add("SUMMARY", summary)
    return event


class ReserveDateTests(unittest.TestCase):
    def test_september_page_identifies_both_reserve_games(self):
        reserves = reserve_matchups(SEPTEMBER_HTML)
        self.assertEqual(
            reserves,
            {
                ("2027-09-10", "Yomiuri", "Hiroshima"),
                ("2027-09-26", "Yomiuri", "Yakult"),
            },
        )

    def test_reserve_and_actual_game_for_same_matchup_is_not_excluded(self):
        source = """
        <link rel="canonical" href="https://npb.jp/games/2027/schedule_09_detail.html">
        <div id="schedule_detail"><table>
        <tr id="date0910"><td><div class="team1">広島</div>
        <div class="cancel">(予備日)</div><div class="team2">巨人</div></td></tr>
        <tr id="date0910"><td><div class="team1">広島</div>
        <div class="state">-</div><div class="team2">巨人</div></td></tr>
        </table></div>
        """
        self.assertEqual(reserve_matchups(source), set())

    def test_missing_schedule_and_bad_reserve_date_fail(self):
        url = '<link href="https://npb.jp/games/2027/schedule_09_detail.html">'
        with self.assertRaises(ValueError):
            reserve_matchups(url)
        with self.assertRaises(ValueError):
            reserve_matchups(
                url + '<div id="schedule_detail"><tr id="date0831">'
                '<div class="team1">広島</div><div class="cancel">予備日</div>'
                '<div class="team2">巨人</div></tr></div>'
            )

    def test_explicit_reserve_flag_is_rejected(self):
        contents = {
            "schema_version": 1,
            "games": [
                {"date": "2027-09-10", "home": "広島", "away": "巨人", "is_reserve": True},
                {"date": "2027-09-11", "home": "広島", "away": "巨人"},
            ],
        }
        with redirect_stdout(StringIO()):
            games = validate_games(contents)
        self.assertEqual([game["date"] for game in games], ["2027-09-11"])
        contents["games"][0]["is_reserve"] = "true"
        with self.assertRaises(ValueError):
            validate_games(contents)

    def test_google_reserve_is_not_saved_and_confirmed_event_is_saved(self):
        old = google_event("previous", "Yomiuri @ Hiroshima")
        reserve = google_event("previous", "予備日 Yomiuri @ Hiroshima")
        confirmed = google_event("confirmed", "Yomiuri @ Hiroshima")
        with redirect_stdout(StringIO()):
            merged = save_snapshot.merge_source_events(
                [reserve, confirmed], {str(old["UID"]): old}
            )
        self.assertEqual(list(merged), ["confirmed"])

    def test_google_event_can_be_added_after_reserve_becomes_a_game(self):
        reserve = google_event("same-uid", "予備日 Yomiuri @ Hiroshima")
        confirmed = google_event("same-uid", "Yomiuri @ Hiroshima")
        with redirect_stdout(StringIO()):
            merged = save_snapshot.merge_source_events([reserve], {})
        self.assertEqual(merged, {})
        merged = save_snapshot.merge_source_events([confirmed], merged)
        self.assertEqual(list(merged), ["same-uid"])

    def test_scored_npb_result_is_not_removed_by_reserve_page(self):
        result = build_event({
            "date": "2027-09-10", "away": "Yomiuri", "home": "Hiroshima",
            "away_score": 2, "home_score": 1,
        })
        with TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "games.json"
            source = september_source(root)
            with patch.object(save_snapshot, "SNAPSHOT_DIRECTORY", root):
                save_snapshot.save_snapshot([result])
                with (
                    patch.object(import_npb_schedule, "request_games", return_value={"schema_version": 1, "games": []}),
                    patch.object(import_npb_schedule, "ROOT", root),
                    patch.dict("os.environ", {"GEMINI_APIKEY": "test-key"}),
                    patch.object(sys, "argv", ["import_npb_schedule.py", "--source", str(source), "--json-output", str(output)]),
                    redirect_stdout(StringIO()),
                ):
                    import_npb_schedule.main()
                snapshot = save_snapshot.load_snapshot(2027)
        self.assertEqual(list(snapshot), [str(result["UID"])])

    def test_import_filters_reserves_and_removes_prior_npb_placeholders(self):
        reserve = build_event({"date": "2027-09-10", "away": "Yomiuri", "home": "Hiroshima"})
        confirmed = {"date": "2027-09-11", "away": "巨人", "home": "広島"}
        ai_output = {
            "schema_version": 1,
            "games": [
                {"date": "2027-09-10", "away": "巨人", "home": "広島"},
                {"date": "2027-09-26", "away": "巨人", "home": "ヤクルト"},
                confirmed,
            ],
        }
        with TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "games.json"
            source = september_source(root)
            with patch.object(save_snapshot, "SNAPSHOT_DIRECTORY", root):
                save_snapshot.save_snapshot([reserve])
                with (
                    patch.object(import_npb_schedule, "request_games", return_value=ai_output),
                    patch.object(import_npb_schedule, "ROOT", root),
                    patch.dict("os.environ", {"GEMINI_APIKEY": "test-key"}),
                    patch.object(sys, "argv", ["import_npb_schedule.py", "--source", str(source), "--json-output", str(output)]),
                    redirect_stdout(StringIO()),
                ):
                    import_npb_schedule.main()
                saved_games = json.loads(output.read_text(encoding="utf-8"))
                self.assertEqual([game["date"] for game in saved_games["games"]], ["2027-09-11"])
                with (
                    patch.object(import_npb_schedule, "ROOT", root),
                    patch.object(sys, "argv", ["import_npb_schedule.py", "--games-json", str(output)]),
                    redirect_stdout(StringIO()),
                ):
                    import_npb_schedule.main()
                snapshot = save_snapshot.load_snapshot(2027)
        self.assertEqual(len(snapshot), 1)
        event = next(iter(snapshot.values()))
        self.assertEqual(event.decoded("DTSTART").isoformat(), "2027-09-11")


if __name__ == "__main__":
    unittest.main()
