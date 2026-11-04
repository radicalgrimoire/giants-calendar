import json
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from icalendar import Calendar, Event

import generate_calendar
import save_snapshot
from generate_calendar import JST, select_games
from import_npb_schedule import build_event, merge_npb_events


def google_event(
    uid: str = "google-test",
    hour: int | None = 18,
    summary: str = "Chunichi @ Yomiuri",
) -> Event:
    event = Event()
    event.add("UID", uid)
    event.add("DTSTAMP", datetime(2026, 11, 1, tzinfo=timezone.utc))
    start = date(2027, 3, 26) if hour is None else datetime(2027, 3, 26, hour, tzinfo=JST)
    event.add("DTSTART", start)
    event.add("DTEND", start + (timedelta(days=1) if hour is None else timedelta(hours=3)))
    event.add("SUMMARY", summary)
    return event


def npb_event(*, start_at: str | None = None, scored: bool = False) -> Event:
    game = {"date": "2027-03-26", "home": "Yomiuri", "away": "Chunichi"}
    if start_at is not None:
        game["start_at"] = start_at
    if scored:
        game.update({"home_score": 4, "away_score": 2})
    return build_event(game)


def events_by_uid(*events: Event) -> dict[str, Event]:
    return {str(event["UID"]): event for event in events}


class CalendarSelectionTests(unittest.TestCase):
    def test_snapshot_keeps_npb_and_google_entries(self):
        npb = npb_event()
        google = google_event()
        merged = save_snapshot.merge_source_events([google], events_by_uid(npb))
        self.assertEqual(set(merged), {str(npb["UID"]), str(google["UID"])})
        self.assertNotIsInstance(merged[str(npb["UID"])].decoded("DTSTART"), datetime)

    def test_timed_game_wins_over_all_day(self):
        npb = npb_event()
        google = google_event()
        self.assertEqual(list(select_games(events_by_uid(npb, google))), [str(google["UID"])])

    def test_selected_google_game_retains_npb_venue(self):
        npb = npb_event()
        npb.add("LOCATION", "official venue")
        google = google_event()
        selected = select_games(events_by_uid(npb, google))
        self.assertEqual(str(selected["google-test"]["LOCATION"]), "official venue")
        output = generate_calendar.build_calendar(list(selected.values()), 2027, {})
        event = next(item for item in output.walk() if item.name == "VEVENT")
        self.assertEqual(str(event["LOCATION"]), "official venue")
        output_override = generate_calendar.build_calendar(
            list(selected.values()), 2027, {date(2027, 3, 26): "local override"}
        )
        event_override = next(item for item in output_override.walk() if item.name == "VEVENT")
        self.assertEqual(str(event_override["LOCATION"]), "local override")

    def test_scored_game_wins_over_timed_even_if_all_day(self):
        scored = google_event("result", None, "Chunichi (3) @ Yomiuri (5)")
        timed = npb_event(start_at="18:00")
        self.assertEqual(list(select_games(events_by_uid(scored, timed))), ["result"])

    def test_scored_npb_wins_over_scored_google_when_equally_timed(self):
        npb = npb_event(start_at="18:00", scored=True)
        google = google_event(summary="Chunichi (3) @ Yomiuri (5)")
        self.assertEqual(list(select_games(events_by_uid(google, npb))), [str(npb["UID"])])

    def test_aliases_are_normalized_and_reversed_matchups_are_distinct(self):
        npb = npb_event()
        google = google_event(summary="中日ドラゴンズ @ 読売ジャイアンツ")
        reverse = google_event("reverse", 18, "Yomiuri @ Chunichi")
        selected = select_games(events_by_uid(npb, google, reverse))
        self.assertEqual(set(selected), {"google-test", "reverse"})

    def test_unrecognized_titles_are_not_discarded(self):
        first = google_event("first", summary="unknown event")
        second = google_event("second", summary="unknown event")
        self.assertEqual(len(select_games(events_by_uid(first, second))), 2)

    def test_npb_reimport_keeps_google_and_existing_npb_results(self):
        npb = npb_event(start_at="17:00", scored=True)
        google = google_event()
        merged = merge_npb_events(events_by_uid(npb, google), [npb_event()])
        self.assertEqual(set(merged), {str(npb["UID"]), str(google["UID"])})
        self.assertEqual(merged[str(npb["UID"])].decoded("DTSTART").hour, 17)
        self.assertEqual(str(merged[str(npb["UID"])]["SUMMARY"]), "Chunichi (2) @ Yomiuri (4)")

    def test_snapshot_to_games_and_calendar(self):
        npb = npb_event()
        google = google_event()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch.object(save_snapshot, "SNAPSHOT_DIRECTORY", root),
                patch.object(generate_calendar, "SNAPSHOT_DIRECTORY", root),
                patch.object(generate_calendar, "GAMES_PATH", root / "games.json"),
                patch.object(
                    generate_calendar,
                    "filter_games",
                    side_effect=lambda events, now: generate_calendar_filter(
                        events, datetime(2026, 1, 1, tzinfo=timezone.utc)
                    ),
                ),
            ):
                save_snapshot.save_snapshot([npb])
                save_snapshot.save_snapshot([google])
                snapshot = json.loads((root / "snapshot-giants-2027.json").read_text(encoding="utf-8"))
                self.assertEqual(len(snapshot["events"]), 2)
                games, calendar = generate_calendar.generate_calendar(2027)
                generate_calendar.save_games(games)
                records = json.loads((root / "games.json").read_text(encoding="utf-8"))
                self.assertEqual(len(records["events"]), 1)
                self.assertEqual(records["events"][0]["uid"], "google-test")
                output = Calendar.from_ical(calendar.to_ical())
                events = [event for event in output.walk() if event.name == "VEVENT"]
                self.assertEqual(len(events), 1)
                self.assertEqual(events[0].decoded("DTSTART"), datetime(2027, 3, 26, 18, tzinfo=JST))


generate_calendar_filter = generate_calendar.filter_games


if __name__ == "__main__":
    unittest.main()
