"""Load and classify Japanese national holidays and substitute holidays."""

import csv
import io
from datetime import date, datetime
from pathlib import Path
from urllib.request import urlopen

HOLIDAYS_URL = "https://www8.cao.go.jp/chosei/shukujitsu/syukujitsu.csv"


def parse_holidays(contents: bytes, year: int) -> set[date]:
    reader = csv.reader(io.StringIO(contents.decode("cp932"), newline=""))
    header = next(reader, None)
    if header != ["国民の祝日・休日月日", "国民の祝日・休日名称"]:
        raise ValueError("祝日CSVのヘッダーが不正です")
    holidays = set()
    for line_number, row in enumerate(reader, start=2):
        if len(row) != 2 or not row[1].strip():
            raise ValueError(f"祝日CSVの{line_number}行目が不正です")
        try:
            holiday = datetime.strptime(row[0], "%Y/%m/%d").date()
        except ValueError as error:
            raise ValueError(f"祝日CSVの{line_number}行目の日付が不正です") from error
        if holiday.year == year:
            holidays.add(holiday)
    if not holidays:
        raise ValueError(f"祝日CSVに{year}年の祝日・休日がありません")
    return holidays


def load_holidays(path: Path | None, year: int) -> set[date]:
    if path is None:
        with urlopen(HOLIDAYS_URL, timeout=30) as response:
            contents = response.read()
    else:
        contents = path.read_bytes()
    return parse_holidays(contents, year)


def is_weekend_or_holiday(day: date, holidays: set[date]) -> bool:
    return day.weekday() >= 5 or day in holidays
