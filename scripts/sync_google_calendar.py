from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

from icalendar import Calendar


ROOT = Path(__file__).resolve().parents[1]
ICS_PATH = ROOT / "giants.ics"
SYNC_MARKER = "giantsCalendarSync"
API_RETRIES = 6


def google_event_id(uid: str) -> str:
    return hashlib.sha256(uid.encode("utf-8")).hexdigest()


def event_datetime(value, property_name: str) -> dict[str, str]:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError(f"{property_name} にタイムゾーンがありません")
        result = {"dateTime": value.isoformat()}
        return result
    if isinstance(value, date):
        return {"date": value.isoformat()}
    raise ValueError(f"{property_name} の形式が不正です")


def to_google_event(event) -> dict:
    uid = event.get("UID")
    if uid is None:
        raise ValueError("VEVENT に UID がありません")

    start_property = event.get("DTSTART")
    end_property = event.get("DTEND")
    if start_property is None or end_property is None:
        raise ValueError(f"VEVENT に DTSTART または DTEND がありません: {uid}")

    start = event_datetime(start_property.dt, "DTSTART")
    end = event_datetime(end_property.dt, "DTEND")
    if "dateTime" in start:
        timezone_id = start_property.params.get("TZID")
        if timezone_id:
            start["timeZone"] = str(timezone_id)
            end["timeZone"] = str(timezone_id)

    status = str(event.get("STATUS", "CONFIRMED")).lower()
    if status not in {"confirmed", "tentative", "cancelled"}:
        raise ValueError(f"VEVENT の STATUS が不正です: {uid} ({status})")

    result = {
        "id": google_event_id(str(uid)),
        "summary": str(event.get("SUMMARY", "")),
        "description": str(event.get("DESCRIPTION", "")),
        "location": str(event.get("LOCATION", "")),
        "start": start,
        "end": end,
        "status": status,
        "extendedProperties": {
            "private": {
                SYNC_MARKER: "true",
                "sourceUid": str(uid),
            }
        },
    }
    return result


def list_managed_events(service, calendar_id: str) -> dict[str, dict]:
    events = {}
    page_token = None
    while True:
        response = (
            service.events()
            .list(
                calendarId=calendar_id,
                privateExtendedProperty=f"{SYNC_MARKER}=true",
                maxResults=2500,
                pageToken=page_token,
            )
            .execute(num_retries=API_RETRIES)
        )
        for event in response.get("items", []):
            events[event["id"]] = event
        page_token = response.get("nextPageToken")
        if not page_token:
            return events


def event_matches(existing: dict, desired: dict) -> bool:
    fields = (
        "summary",
        "description",
        "location",
        "start",
        "end",
        "status",
        "extendedProperties",
    )
    return all(existing.get(field) == desired.get(field) for field in fields)


def sync_events(
    service, calendar_id: str, desired_events: list[dict]
) -> tuple[int, int, int]:
    existing_events = list_managed_events(service, calendar_id)
    desired_ids = set()
    created = updated = 0

    for event in desired_events:
        event_id = event["id"]
        if event_id in desired_ids:
            raise ValueError(f"ICS に重複した UID があります: {event_id}")
        desired_ids.add(event_id)

        existing = existing_events.pop(event_id, None)
        if existing is None:
            service.events().insert(
                calendarId=calendar_id, body=event
            ).execute(num_retries=API_RETRIES)
            created += 1
        elif not event_matches(existing, event):
            service.events().update(
                calendarId=calendar_id,
                eventId=event_id,
                body=event,
            ).execute(num_retries=API_RETRIES)
            updated += 1

    for event_id in existing_events:
        service.events().delete(
            calendarId=calendar_id, eventId=event_id
        ).execute(num_retries=API_RETRIES)

    return created, updated, len(existing_events)


def sync_calendar() -> tuple[int, int, int]:
    credentials_json = os.environ.get("GIANTS_CALENDER_API")
    calendar_id = os.environ.get("GIANTS_CALENDAR_ID")
    if not credentials_json:
        raise ValueError("GIANTS_CALENDER_API Secret が設定されていません")
    if not calendar_id:
        raise ValueError("GIANTS_CALENDAR_ID Repository variable が設定されていません")

    credentials_info = json.loads(credentials_json)
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    credentials = service_account.Credentials.from_service_account_info(
        credentials_info,
        scopes=["https://www.googleapis.com/auth/calendar.events"],
    )
    service = build("calendar", "v3", credentials=credentials, cache_discovery=False)

    calendar = Calendar.from_ical(ICS_PATH.read_bytes())
    desired_events = [to_google_event(event) for event in calendar.walk("VEVENT")]
    return sync_events(service, calendar_id, desired_events)


def main() -> None:
    created, updated, deleted = sync_calendar()
    print(
        "Google Calendar sync complete: "
        f"{created} created, {updated} updated, {deleted} deleted"
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Google Calendar sync failed: {error}", file=sys.stderr)
        raise
