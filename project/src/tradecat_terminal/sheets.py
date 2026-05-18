from __future__ import annotations

import csv
from collections.abc import Sequence
from io import StringIO
from urllib.parse import urlparse
from urllib.request import getproxies, proxy_bypass

import urllib3
from urllib3.exceptions import (
    ConnectTimeoutError,
    HTTPError,
    MaxRetryError,
    NameResolutionError,
    NewConnectionError,
    ReadTimeoutError,
)
from urllib3.util.retry import Retry

DEFAULT_ATTEMPTS = 3
RETRY_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
USER_AGENT = "tradecat/0.1"


class RemoteCsvError(RuntimeError):
    def __init__(
        self,
        *,
        code: str,
        kind: str,
        message: str,
        hint: str,
        retryable: bool,
        status: int | None = None,
        attempts: int = DEFAULT_ATTEMPTS,
        url: str = "",
    ) -> None:
        self.code = code
        self.kind = kind
        self.hint = hint
        self.retryable = retryable
        self.status = status
        self.attempts = attempts
        self.url_host = urlparse(url).netloc if url else ""
        super().__init__(message)

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "code": self.code,
            "kind": self.kind,
            "message": str(self),
            "hint": self.hint,
            "retryable": self.retryable,
            "attempts": self.attempts,
        }
        if self.status is not None:
            payload["status"] = self.status
        if self.url_host:
            payload["url_host"] = self.url_host
        return payload


def fetch_csv_body(url: str, timeout: float = 30.0, *, attempts: int = DEFAULT_ATTEMPTS) -> str:
    retry = Retry(
        total=max(0, int(attempts) - 1),
        connect=max(0, int(attempts) - 1),
        read=max(0, int(attempts) - 1),
        status=max(0, int(attempts) - 1),
        allowed_methods=frozenset({"GET"}),
        status_forcelist=RETRY_STATUS_CODES,
        backoff_factor=0.5,
        backoff_jitter=0.2,
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    manager_kwargs = {
        "retries": retry,
        "timeout": urllib3.Timeout(connect=max(0.5, min(float(timeout), 5.0)), read=max(0.5, float(timeout))),
        "headers": {"User-Agent": USER_AGENT},
    }
    proxy_url = _proxy_url_for(url)
    http = urllib3.ProxyManager(proxy_url, **manager_kwargs) if proxy_url else urllib3.PoolManager(
        **manager_kwargs
    )
    try:
        response = http.request("GET", url)
    except Exception as exc:
        raise _classify_transport_error(exc, url=url, attempts=attempts) from exc
    status = int(response.status)
    if status >= 400:
        raise RemoteCsvError(
            code="remote_http_status",
            kind="http",
            message=f"remote returned HTTP {status}",
            hint=_http_hint(status),
            retryable=status in RETRY_STATUS_CODES,
            status=status,
            attempts=attempts,
            url=url,
        )
    try:
        return response.data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise RemoteCsvError(
            code="remote_decode_error",
            kind="decode",
            message=f"remote CSV decode failed: {exc}",
            hint="远端返回内容不是 UTF-8 CSV；稍后重试或检查公开表格导出格式。",
            retryable=False,
            attempts=attempts,
            url=url,
        ) from exc


def _proxy_url_for(url: str) -> str | None:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if host and proxy_bypass(host):
        return None
    proxies = getproxies()
    proxy = proxies.get(parsed.scheme.lower()) or proxies.get("all")
    return str(proxy) if proxy else None


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
    if header_index < len(rows) and is_section_header_row(rows[header_index]):
        return sectioned_data_rows(rows, header_index)
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


def is_section_header_row(row: Sequence[str]) -> bool:
    cells = [str(cell).strip() for cell in row]
    if not cells or not cells[0] or is_public_top_row(row):
        return False
    tail = [cell for cell in cells[1:] if cell]
    return "序号" in tail and any(cell in {"交易对", "合约代码", "币种符号", "symbol", "Symbol", "SYMBOL"} for cell in tail)


def sectioned_data_rows(matrix: list[list[str]], start_index: int) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    section_title = ""
    section_headers: list[str] = []
    for row_index, raw in enumerate(matrix[start_index:], start=start_index + 1):
        if is_section_header_row(raw):
            section_title = str(raw[0]).strip()
            section_headers = normalize_headers([str(cell) for cell in raw[1:]])
            continue
        if not section_headers:
            continue
        section_values = [str(cell) for cell in raw[1:]]
        if not any(cell.strip() for cell in section_values):
            continue
        padded = [*section_values, *([""] * max(0, len(section_headers) - len(section_values)))]
        values = {"榜单": section_title, "榜单名": section_title, "源行号": str(row_index)}
        values.update({section_headers[index]: padded[index] for index in range(len(section_headers))})
        rows.append(values)
    return rows


def normalize_headers(headers: Sequence[str]) -> list[str]:
    normalized: list[str] = []
    seen: dict[str, int] = {}
    for index, header in enumerate(headers, start=1):
        name = header.strip() or f"column_{index}"
        count = seen.get(name, 0) + 1
        seen[name] = count
        normalized.append(name if count == 1 else f"{name}_{count}")
    return normalized


def _classify_transport_error(exc: Exception, *, url: str, attempts: int) -> RemoteCsvError:
    reason = exc.reason if isinstance(exc, MaxRetryError) else exc
    if isinstance(reason, (NameResolutionError, NewConnectionError)):
        return RemoteCsvError(
            code="remote_dns_or_connect_error",
            kind="network",
            message=f"remote connection failed: {reason}",
            hint="无法连接公开数据源；检查 DNS、代理或网络后重试。",
            retryable=True,
            attempts=attempts,
            url=url,
        )
    if isinstance(reason, (ConnectTimeoutError, ReadTimeoutError)):
        return RemoteCsvError(
            code="remote_timeout",
            kind="timeout",
            message=f"remote request timed out after {attempts} attempt(s)",
            hint="网络超时；可执行 tradecat sync-all --timeout 10 或稍后重试。",
            retryable=True,
            attempts=attempts,
            url=url,
        )
    if isinstance(exc, HTTPError) or isinstance(reason, HTTPError):
        return RemoteCsvError(
            code="remote_transport_error",
            kind="network",
            message=f"remote transport error: {reason}",
            hint="远端网络链路失败；保留本地缓存并稍后重试。",
            retryable=True,
            attempts=attempts,
            url=url,
        )
    return RemoteCsvError(
        code="remote_unknown_error",
        kind="unknown",
        message=str(reason),
        hint="未知远端错误；执行 tradecat doctor --verbose 查看诊断信息。",
        retryable=False,
        attempts=attempts,
        url=url,
    )


def _http_hint(status: int) -> str:
    if status == 429:
        return "远端限流；等待一段时间后重试，CI 会保留失败诊断。"
    if status in {500, 502, 503, 504}:
        return "远端服务临时不可用；本地缓存不会被清空，稍后重试。"
    return "远端拒绝当前请求；检查公开表格权限或导出链接。"
