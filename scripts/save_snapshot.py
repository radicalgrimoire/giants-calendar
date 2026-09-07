import copy
import json
from datetime import date, datetime, time, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from icalendar import Calendar, Event


SOURCE_URL = (
    "https://calendar.google.com/calendar/ical/"
    "npb_-m-0132%257e_h_%2559omiuri%2B%2547iants%23sports%40group.v.calendar.google.com/"
    "public/basic.ics"
)
ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_DIRECTORY = ROOT / "data" / "snapshots"
JST = ZoneInfo("Asia/Tokyo")


def fetch_source() -> bytes:
    request = Request(SOURCE_URL, headers={"User-Agent": "giants-calendar/1.0"})
    with urlopen(request, timeout=30) as response:
        return response.read()


def event_start(event: Event) -> datetime:
    value = event.decoded("DTSTART")
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=timezone.utc)
    raise ValueError("VEVENT に DTSTART がありません")


def event_uid(event: Event) -> str:
    uid = event.get("UID")
    if uid is None:
        raise ValueError("VEVENT に UID がありません")
    return str(uid)


def event_to_record(event: Event) -> dict[str, str]:
    return {
        "uid": event_uid(event),
        "start": event_start(event).isoformat(),
        "ical": event.to_ical().decode("utf-8"),
    }


def snapshot_path(year: int) -> Path:
    return SNAPSHOT_DIRECTORY / f"snapshot-giants-{year}.json"


def load_snapshot(year: int) -> dict[str, Event]:
    path = snapshot_path(year)
    if not path.exists():
        return {}
    contents = json.loads(path.read_text(encoding="utf-8"))
    return {
        record["uid"]: Event.from_ical(record["ical"].encode("utf-8"))
        for record in contents["events"]
    }


def merge_source_events(source_events: list[Event], snapshot: dict[str, Event]) -> dict[str, Event]:
    merged = {uid: copy.deepcopy(event) for uid, event in snapshot.items()}
    for event in source_events:
        merged[event_uid(event)] = copy.deepcopy(event)
    return merged


def save_snapshot(events: list[Event]) -> None:
    events_by_year: dict[int, list[Event]] = {}
    for event in events:
        year = event_start(event).astimezone(JST).year
        events_by_year.setdefault(year, []).append(event)

    for year, yearly_events in events_by_year.items():
        merged_events = merge_source_events(yearly_events, load_snapshot(year))
        records = sorted(
            (event_to_record(event) for event in merged_events.values()),
            key=lambda record: (record["start"], record["uid"]),
        )
        path = snapshot_path(year)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"schema_version": 1, "events": records},
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )


def main() -> None:
    source = Calendar.from_ical(fetch_source())
    source_events = [
        component for component in source.walk() if component.name == "VEVENT"
    ]
    save_snapshot(source_events)


if __name__ == "__main__":
    main()