#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import socket
import sys
from io import StringIO
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

USER_AGENT = "tradecat-request/0.1"
CONTRACT_VERSION = "1.0.0"
REQUEST_SCHEMA = "tradecat.request_result.v1"
REQUEST_DATASET_LIST_SCHEMA = "tradecat.request_dataset_list.v1"
DEFAULT_REGISTRY_URL = (
    "https://raw.githubusercontent.com/tukuaiai/tradecat/develop/project/src/tradecat_terminal/dataset_registry.json"
)
REGISTRY_URL_ENV = "TRADECAT_REQUEST_REGISTRY_URL"


def main(argv: list[str] | None = None) -> int:
    configure_stdio()
    parser = argparse.ArgumentParser(description="TradeCat 一次性公开数据请求；无需安装，无本地缓存。")
    parser.add_argument("dataset_key", nargs="?", help="dataset_key，例如 event_stream")
    parser.add_argument("--format", choices=("table", "json", "jsonl", "csv", "raw"), default="table")
    parser.add_argument("--limit", type=int, default=50, help="最多输出业务数据行；0 表示不限制")
    parser.add_argument("--timeout", type=float, default=8.0, help="网络请求超时秒数")
    parser.add_argument(
        "--registry-url",
        default=os.environ.get(REGISTRY_URL_ENV, DEFAULT_REGISTRY_URL),
        help=f"dataset registry JSON URL；默认读取 {REGISTRY_URL_ENV} 或 GitHub develop",
    )
    parser.add_argument("--meta", action="store_true", help="只输出顶部元信息")
    parser.add_argument("--headers", action="store_true", help="只输出表头")
    parser.add_argument("--datasets", action="store_true", help="列出可用 dataset")
    args = parser.parse_args(argv)
    if not args.dataset_key and not args.datasets:
        return emit_error(
            "需要 dataset_key；可用 --datasets 查看",
            as_json=args.format == "json",
            code="missing_dataset_key",
            kind="validation",
            hint="执行 request.py --datasets 查看可用 dataset_key。",
        )
    try:
        registry = load_registry(args.registry_url, timeout=args.timeout)
    except Exception as exc:
        return emit_error(exc, as_json=args.format == "json", **classify_request_error(exc))

    if args.datasets:
        datasets = [
            {"key": key, "data_mode": spec["data_mode"], "tab_name": spec["tab_name"]}
            for key, spec in registry["datasets"].items()
            if spec.get("active", True)
        ]
        if args.format == "json":
            print(
                json.dumps(
                    {
                        "schema": REQUEST_DATASET_LIST_SCHEMA,
                        "schema_version": CONTRACT_VERSION,
                        "ok": True,
                        "datasets": datasets,
                    },
                    ensure_ascii=False,
                )
            )
            return 0
        for key, spec in registry["datasets"].items():
            if not spec.get("active", True):
                continue
            print(f"{key}\tmode={spec['data_mode']}\ttab={spec['tab_name']}")
        return 0

    try:
        body = fetch_body(dataset_url(registry, args.dataset_key), timeout=args.timeout)
    except Exception as exc:
        return emit_error(exc, as_json=args.format == "json", **classify_request_error(exc))
    if args.format == "raw":
        print(body, end="" if body.endswith("\n") else "\n")
        return 0

    try:
        matrix = parse_matrix(body)
        meta = top_lines(matrix)
        header_index = find_header_row_index(matrix)
        headers = normalize_headers(matrix[header_index] if header_index < len(matrix) else [])
        rows = data_rows(matrix, header_index, headers)
    except Exception as exc:
        return emit_error(
            exc,
            as_json=args.format == "json",
            code="remote_parse_error",
            kind="parse",
            hint="远端返回内容不是预期 CSV；检查公开表格导出格式。",
            retryable=False,
        )
    if args.limit > 0:
        rows = rows[: args.limit]

    if args.meta:
        print("\n".join(meta))
        return 0
    if args.headers:
        print(json.dumps(headers, ensure_ascii=False))
        return 0
    if args.format == "json":
        print(
            json.dumps(
                {
                    "schema": REQUEST_SCHEMA,
                    "schema_version": CONTRACT_VERSION,
                    "ok": True,
                    "dataset_key": args.dataset_key,
                    "meta": meta,
                    "headers": headers,
                    "rows": rows,
                },
                ensure_ascii=False,
            )
        )
        return 0
    if args.format == "jsonl":
        for row in rows:
            print(json.dumps(row, ensure_ascii=False))
        return 0
    if args.format == "csv":
        writer = csv.DictWriter(sys.stdout, fieldnames=headers, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        return 0
    print(render_table(rows, headers=headers))
    return 0


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


def load_registry(url: str, *, timeout: float) -> dict[str, dict]:
    payload = json.loads(fetch_body(url, timeout=timeout))
    if not isinstance(payload, dict) or not isinstance(payload.get("workbooks"), dict) or not isinstance(
        payload.get("datasets"), dict
    ):
        raise ValueError("dataset registry 格式错误")
    return {"workbooks": payload["workbooks"], "datasets": payload["datasets"]}


def dataset_url(registry: dict[str, dict], dataset_key: str) -> str:
    try:
        spec = registry["datasets"][dataset_key]
    except KeyError as exc:
        available = ", ".join(sorted(registry["datasets"]))
        raise ValueError(f"未知 dataset_key: {dataset_key}; 可用值: {available}") from exc
    if not spec.get("active", True):
        raise ValueError(f"dataset_key 已停用: {dataset_key}")
    workbook_key = str(spec["workbook_key"])
    try:
        workbook = registry["workbooks"][workbook_key]
    except KeyError as exc:
        raise ValueError(f"dataset {dataset_key} 引用了未知 workbook: {workbook_key}") from exc
    spreadsheet_id = str(workbook["spreadsheet_id"])
    query = urlencode({"format": "csv", "gid": str(spec["gid"])})
    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?{query}"


def fetch_body(url: str, *, timeout: float) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8-sig")


def emit_error(
    error,
    *,
    as_json: bool,
    code: str,
    kind: str,
    hint: str,
    retryable: bool,
    status: int | None = None,
) -> int:
    message = str(error)
    if as_json:
        payload = {
            "schema": REQUEST_SCHEMA,
            "schema_version": CONTRACT_VERSION,
            "ok": False,
            "error": {
                "code": code,
                "kind": kind,
                "message": message,
                "hint": hint,
                "retryable": retryable,
            },
        }
        if status is not None:
            payload["error"]["status"] = status
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(f"request error: {message}", file=sys.stderr)
    return 2 if kind == "validation" else 1


def classify_request_error(exc: Exception) -> dict:
    if isinstance(exc, HTTPError):
        status = int(exc.code)
        return {
            "code": "remote_http_status",
            "kind": "http",
            "hint": "远端拒绝当前请求；检查公开表格权限或稍后重试。",
            "retryable": status in {429, 500, 502, 503, 504},
            "status": status,
        }
    if isinstance(exc, TimeoutError) or isinstance(exc, socket.timeout):
        return {
            "code": "remote_timeout",
            "kind": "timeout",
            "hint": "网络超时；增加 --timeout 或稍后重试。",
            "retryable": True,
        }
    if isinstance(exc, URLError):
        return {
            "code": "remote_transport_error",
            "kind": "network",
            "hint": "远端网络链路失败；检查 DNS、代理或网络后重试。",
            "retryable": True,
        }
    if isinstance(exc, ValueError):
        return {
            "code": "invalid_request",
            "kind": "validation",
            "hint": "检查 dataset_key、registry URL 或远端 JSON/CSV 格式。",
            "retryable": False,
        }
    return {
        "code": "request_failed",
        "kind": "runtime",
        "hint": "执行 --datasets 确认入口可用，必要时改用安装版 tradecat doctor。",
        "retryable": False,
    }


def parse_matrix(body: str) -> list[list[str]]:
    return list(csv.reader(StringIO(body)))


def top_lines(matrix: list[list[str]]) -> list[str]:
    lines: list[str] = []
    for row in matrix[:1]:
        for value in row:
            text = str(value).strip()
            if not text:
                continue
            lines.extend(line.strip() for line in text.splitlines() if line.strip())
    return lines


def find_header_row_index(matrix: list[list[str]]) -> int:
    for index, row in enumerate(matrix):
        non_empty = [cell.strip() for cell in row if cell.strip()]
        if len(non_empty) >= 2 and not is_top_row(row):
            return index
    return 0


def is_top_row(row: list[str]) -> bool:
    first = row[0].strip() if row else ""
    return first.startswith(("https://", "http://", "数据源，")) or first == "数据源"


def normalize_headers(headers: list[str]) -> list[str]:
    result: list[str] = []
    seen: dict[str, int] = {}
    for index, header in enumerate(headers, start=1):
        name = header.strip() or f"column_{index}"
        count = seen.get(name, 0) + 1
        seen[name] = count
        result.append(name if count == 1 else f"{name}_{count}")
    return result


def data_rows(matrix: list[list[str]], header_index: int, headers: list[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for raw in matrix[header_index + 1 :]:
        if not any(cell.strip() for cell in raw):
            continue
        padded = [*raw, *([""] * max(0, len(headers) - len(raw)))]
        rows.append({headers[index]: padded[index] for index in range(len(headers))})
    return rows


def render_table(rows: list[dict[str, str]], *, headers: list[str]) -> str:
    if not rows:
        return "(empty)"
    widths = [len(header) for header in headers]
    for row in rows:
        for index, header in enumerate(headers):
            widths[index] = max(widths[index], len(str(row.get(header, ""))))
    border = "+" + "+".join("-" * (width + 2) for width in widths) + "+"
    header_line = "|" + "|".join(f" {header:<{widths[index]}} " for index, header in enumerate(headers)) + "|"
    lines = [border, header_line, border]
    for row in rows:
        lines.append("|" + "|".join(f" {str(row.get(header, '')):<{widths[index]}} " for index, header in enumerate(headers)) + "|")
    lines.append(border)
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
