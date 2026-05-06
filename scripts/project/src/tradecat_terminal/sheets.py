from __future__ import annotations

import csv
from collections.abc import Sequence
from io import StringIO
from urllib.request import Request, urlopen


def fetch_csv_body(url: str, timeout: float = 30.0) -> str:
    request = Request(url, headers={"User-Agent": "tradecat/0.1"})
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8-sig")


def fetch_csv_rows(url: str, timeout: float = 30.0) -> list[dict[str, str]]:
    return parse_csv_rows(fetch_csv_body(url, timeout=timeout))


def parse_csv_matrix(body: str) -> list[list[str]]:
    return list(csv.reader(StringIO(body)))


def parse_csv_rows(body: str) -> list[dict[str, str]]:
    reader = csv.reader(StringIO(body))
    rows = list(reader)
    if not rows:
        return []
    header_index = find_header_row_index(rows)
    width = max((len(row) for row in rows[header_index:]), default=0)
    raw_headers = [*rows[header_index], *([""] * max(0, width - len(rows[header_index])))]
    headers = normalize_headers(raw_headers)
    result: list[dict[str, str]] = []
    for raw_row in rows[header_index + 1 :]:
        if not any(cell.strip() for cell in raw_row):
            continue
        padded = [*raw_row, *([""] * max(0, len(headers) - len(raw_row)))]
        result.append({headers[index]: padded[index] for index in range(len(headers))})
    return result


def find_header_row_index(rows: list[list[str]]) -> int:
    for index, row in enumerate(rows):
        non_empty = [cell.strip() for cell in row if cell.strip()]
        if len(non_empty) >= 2 and not is_public_top_row(row):
            return index
    return 0


def is_public_top_row(row: Sequence[str]) -> bool:
    first = row[0].strip() if row else ""
    return first.startswith("https://") or first.startswith("http://") or first.startswith("数据源，") or first == "数据源"


def normalize_headers(headers: Sequence[str]) -> list[str]:
    normalized: list[str] = []
    seen: dict[str, int] = {}
    for index, header in enumerate(headers, start=1):
        name = header.strip() or f"column_{index}"
        count = seen.get(name, 0) + 1
        seen[name] = count
        normalized.append(name if count == 1 else f"{name}_{count}")
    return normalized
