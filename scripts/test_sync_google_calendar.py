from __future__ import annotations

import unittest
from datetime import date, datetime

from icalendar import Calendar, Event

from sync_google_calendar import (
    event_datetime,
    event_matches,
    google_event_id,
    sync_events,
    to_google_event,
)


def make_ical_event(*, uid: str = "game-1@example.com") -> Event:
    event = Event()
    event.add("uid", uid)
    event.add("summary", "Giants vs Tigers")
    event.add("dtstart", datetime.fromisoformat("2027-03-26T18:00:00+09:00"))
    event.add("dtend", datetime.fromisoformat("2027-03-26T21:00:00+09:00"))
    event["dtstart"].params["TZID"] = "Asia/Tokyo"
    event["dtend"].params["TZID"] = "Asia/Tokyo"
    return event


class Request:
    def __init__(self, response=None, calls=None):
        self.response = response or {}
        self.calls = calls

    def execute(self, *, num_retries=0):
        if self.calls is not None:
            self.calls.append(("execute", num_retries))
        return self.response


class Events:
    def __init__(self, existing=None):
        self.existing = existing or []
        self.calls = []

    def list(self, **kwargs):
        self.calls.append(("list", kwargs))
        return Request({"items": self.existing}, self.calls)

    def insert(self, **kwargs):
        self.calls.append(("insert", kwargs))
        return Request(calls=self.calls)

    def update(self, **kwargs):
        self.calls.append(("update", kwargs))
        return Request(calls=self.calls)

    def delete(self, **kwargs):
        self.calls.append(("delete", kwargs))
        return Request(calls=self.calls)


class Service:
    def __init__(self, events):
        self._events = events

    def events(self):
        return self._events


class SyncGoogleCalendarTests(unittest.TestCase):
    def test_google_event_id_is_deterministic_and_api_compatible(self):
        event_id = google_event_id("game-1@example.com")
        self.assertEqual(event_id, google_event_id("game-1@example.com"))
        self.assertRegex(event_id, r"^[a-f0-9]{64}$")

    def test_event_datetime_handles_timed_and_all_day_events(self):
        self.assertEqual(
            event_datetime(datetime.fromisoformat("2027-03-26T18:00:00+09:00"), "DTSTART"),
            {"dateTime": "2027-03-26T18:00:00+09:00"},
        )
        self.assertEqual(
            event_datetime(date(2027, 3, 26), "DTSTART"),
            {"date": "2027-03-26"},
        )

    def test_to_google_event_preserves_stable_uid_and_timezone(self):
        google_event = to_google_event(make_ical_event())
        self.assertEqual(google_event["id"], google_event_id("game-1@example.com"))
        self.assertEqual(google_event["start"]["timeZone"], "Asia/Tokyo")
        self.assertEqual(google_event["summary"], "Giants vs Tigers")
        self.assertEqual(
            google_event["extendedProperties"]["private"]["sourceUid"],
            "game-1@example.com",
        )

    def test_event_matches_only_when_synced_fields_match(self):
        expected = to_google_event(make_ical_event())
        self.assertTrue(event_matches(expected.copy(), expected))
        changed = {**expected, "summary": "Changed"}
        self.assertFalse(event_matches(changed, expected))

    def test_sync_inserts_updates_and_deletes_only_managed_events(self):
        desired = to_google_event(make_ical_event())
        changed = {**desired, "summary": "Old summary"}
        stale = {
            "id": "stale-event",
            "extendedProperties": {"private": {"giantsCalendarSync": "true"}},
        }
        events = Events([desired, changed, stale])
        service = Service(events)

        counts = sync_events(service, "calendar@example.com", [desired, {
            **desired,
            "id": "new-event",
        }])

        self.assertEqual(counts, (1, 1, 1))
        self.assertEqual(
            [call[0] for call in events.calls],
            [
                "list",
                "execute",
                "update",
                "execute",
                "insert",
                "execute",
                "delete",
                "execute",
            ],
        )
        delete_call = next(call for call in events.calls if call[0] == "delete")
        self.assertEqual(delete_call[1]["eventId"], "stale-event")
        self.assertTrue(
            all(call[1] == 6 for call in events.calls if call[0] == "execute")
        )


if __name__ == "__main__":
    unittest.main()
