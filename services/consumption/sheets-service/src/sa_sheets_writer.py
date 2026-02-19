# ruff: noqa: UP017
from __future__ import annotations

import hashlib
import json
import os
import time
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.dashboard_variants import VariantTable, compact_cell_multiperiod, vertical_multiperiod


def _col_to_index(col: str) -> int:
    s = (col or "").strip().upper()
    if not s or not s.isalpha():
        raise ValueError(f"invalid_column:{col}")
    idx = 0
    for ch in s:
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx


def _index_to_col(idx: int) -> str:
    n = int(idx)
    if n <= 0:
        raise ValueError(f"invalid_col_index:{idx}")
    out = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        out = chr(ord("A") + rem) + out
    return out


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _rgb(r: float, g: float, b: float) -> dict[str, float]:
    return {"red": float(r), "green": float(g), "blue": float(b)}


def _parse_period_suffix(col: str) -> str:
    s = str(col or "").strip()
    if "@" not in s:
        return ""
    _field, suf = s.rsplit("@", 1)
    return suf.strip()


def _parse_field_group(col: str) -> str:
    s = str(col or "").strip()
    if "@" not in s:
        return s
    field, _suf = s.rsplit("@", 1)
    return field.strip()


def _env_text(key: str, default: str) -> str:
    v = (os.environ.get(key, "") or "").strip()
    return v or default


def _value_type(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "array"
    return "object"


def _flatten_eav(prefix: str, val: Any) -> Iterable[tuple[str, str, str]]:
    """
    返回 (field_path, value_type, value_text) 的序列。
    - 对 object/array：先写容器节点，再递归子节点
    - 对 scalar：写标量节点
    """
    t = _value_type(val)
    path = prefix or "_"
    if t in {"null", "bool", "number", "string"}:
        yield (path, t, "" if val is None else str(val))
        return

    if t == "array":
        yield (path, t, "")
        for i, item in enumerate(val):
            yield from _flatten_eav(f"{path}[{i}]", item)
        return

    # object
    yield (path, t, "")
    if isinstance(val, dict):
        for k, v in val.items():
            child = f"{k}" if path == "_" else f"{path}.{k}"
            yield from _flatten_eav(child, v)


@dataclass(frozen=True)
class BootstrapResult:
    spreadsheet_id: str
    spreadsheet_url: str


class _WriteRateLimiter:
    def __init__(self, limit_per_minute: int) -> None:
        self._limit = max(int(limit_per_minute), 0)
        self._window_seconds = 60.0
        self._ts: deque[float] = deque()

    def acquire(self) -> None:
        if self._limit <= 0:
            return

        while True:
            now = time.monotonic()
            while self._ts and (now - self._ts[0]) >= self._window_seconds:
                self._ts.popleft()

            if len(self._ts) < self._limit:
                self._ts.append(now)
                return

            sleep_for = self._window_seconds - (now - self._ts[0]) + 0.05
            time.sleep(max(sleep_for, 0.05))


class SaSheetsWriter:
    """
    Service Account + Google Sheets API 写入实现（全 CLI）。
    - 支持：创建工作簿、建 tab/表头、写事实表、渲染 dashboard（含合并单元格）
    - 可选：Drive 权限（公开只读/分享给 email）、以及超长 raw 字段落 Drive blob
    """

    def __init__(
        self,
        *,
        spreadsheet_id: str,
        credentials_path: str,
        dashboard_col_l: str,
        dashboard_col_r: str,
        dashboard_mode: str = "replace",
        dashboard_slot_height: int = 260,
        facts_mode: str = "append",
        share_email: str,
        public_read: bool,
        drive_folder_id: str,
        blob_threshold_chars: int,
        timeout_seconds: int = 15,
        schema_mode: str = "full",
        local_meta_path: Path | None = None,
    ) -> None:
        try:
            import google_auth_httplib2  # type: ignore
            import httplib2  # type: ignore
            from google.oauth2.service_account import Credentials  # type: ignore
            from googleapiclient.discovery import build  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "缺少 Google API 依赖：请在 sheets-service 安装 google-api-python-client/google-auth"
            ) from exc

        if not credentials_path:
            raise RuntimeError("缺少 SA 凭证路径：设置 GOOGLE_APPLICATION_CREDENTIALS 或 SHEETS_SA_CREDENTIALS_PATH")

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_file(credentials_path, scopes=scopes)

        # 关键：在部分网络环境下必须走代理（例如 WSL/公司网络）
        # httplib2 默认不读环境变量；这里显式从环境构造 proxy_info。
        proxy_info = httplib2.proxy_info_from_environment()
        base_http = httplib2.Http(proxy_info=proxy_info, timeout=timeout_seconds)
        authed_http = google_auth_httplib2.AuthorizedHttp(creds, http=base_http)

        self._sheets = build("sheets", "v4", http=authed_http, cache_discovery=False)
        self._drive = build("drive", "v3", http=authed_http, cache_discovery=False)

        self._spreadsheet_id = spreadsheet_id
        self._dashboard_col_l = dashboard_col_l
        self._dashboard_col_r = dashboard_col_r
        self._dashboard_mode = (dashboard_mode or "replace").strip().lower()
        self._dashboard_slot_height = max(int(dashboard_slot_height), 1)
        self._facts_mode = (facts_mode or "append").strip().lower()
        self._share_email = share_email
        self._public_read = public_read
        self._drive_folder_id = drive_folder_id
        self._blob_threshold_chars = int(blob_threshold_chars)
        self._timeout_seconds = timeout_seconds
        self._schema_mode = (schema_mode or "full").strip().lower()
        if self._schema_mode not in {"full", "minimal"}:
            self._schema_mode = "full"
        self._local_meta_path = local_meta_path

        # Sheet tabs（要求：全部中文命名；如需定制可用 env 覆盖）
        self._tab_dashboard = _env_text("SHEETS_TAB_DASHBOARD", "看板")
        self._tab_cards_index = _env_text("SHEETS_TAB_CARDS_INDEX", "卡片索引")
        self._tab_card_fields_eav = _env_text("SHEETS_TAB_CARD_FIELDS_EAV", "卡片字段EAV")
        self._tab_card_rows = _env_text("SHEETS_TAB_CARD_ROWS", "卡片明细行")
        self._tab_row_fields_eav = _env_text("SHEETS_TAB_ROW_FIELDS_EAV", "明细字段EAV")
        self._tab_blobs_index = _env_text("SHEETS_TAB_BLOBS_INDEX", "大字段索引")
        self._tab_meta = _env_text("SHEETS_TAB_META", "元数据")

        self._ensured_schema = False
        self._sheet_id_by_title: dict[str, int] = {}
        self._grid_by_title: dict[str, tuple[int, int]] = {}
        self._append_cursor_y = 1

        # Google Sheets 默认配额很低（常见为 60 write req/min/user），不做节流会稳定触发 429。
        write_rpm = int((os.environ.get("SHEETS_SA_WRITE_RPM", "55") or "55").strip())
        self._write_limiter = _WriteRateLimiter(write_rpm)

    def _exec(self, req: Any, *, is_write: bool) -> Any:
        if is_write:
            self._write_limiter.acquire()
        return req.execute()

    # ==================== runtime overrides（用于 CLI/运维） ====================
    def set_dashboard_mode(self, mode: str) -> None:
        self._dashboard_mode = (mode or "").strip().lower() or self._dashboard_mode

    def compute_col_r(self, *, col_l: str, needed_cols: int, min_col_r: str) -> str:
        """
        计算 dashboard 的 col_r：
        - 从 col_l 起，需要容纳 needed_cols 列
        - 同时不小于 min_col_r（避免把用户显式配置的右边界“缩回去”）
        """
        left = _col_to_index(col_l)
        need = max(int(needed_cols), 1)
        want_r = left + need - 1
        try:
            min_r = _col_to_index(min_col_r)
        except Exception:
            min_r = want_r
        return _index_to_col(max(want_r, min_r))

    # ==================== bootstrap ====================
    def bootstrap(self, *, title: str) -> BootstrapResult:
        if not self._spreadsheet_id:
            quota = self._exec(self._drive.about().get(fields="storageQuota"), is_write=False).get("storageQuota", {})
            limit = int(quota.get("limit") or "0")
            usage = int(quota.get("usage") or "0")
            if limit <= 0 or usage >= limit:
                raise RuntimeError(
                    "Service Account 的 Google Drive 存储配额为 0（或已用尽），无法创建新工作簿。"
                    "解决方案：用你的个人账号先创建一个空 Google Sheet（网页端），把它分享给该 SA 邮箱为编辑，"
                    "然后设置 SHEETS_SPREADSHEET_ID 走写入（无需再 bootstrap 创建）。"
                )
            created = self._exec(
                self._sheets.spreadsheets().create(body={"properties": {"title": title}}), is_write=True
            )
            self._spreadsheet_id = created["spreadsheetId"]

        self.ensure_schema()

        if self._drive_folder_id:
            self._move_to_folder(self._drive_folder_id)

        if self._public_read:
            self._set_public_read()

        if self._share_email:
            self._share_to_email(self._share_email, role="writer")

        url = f"https://docs.google.com/spreadsheets/d/{self._spreadsheet_id}"
        return BootstrapResult(spreadsheet_id=self._spreadsheet_id, spreadsheet_url=url)

    def _move_to_folder(self, folder_id: str) -> None:
        file_id = self._spreadsheet_id
        meta = self._exec(self._drive.files().get(fileId=file_id, fields="parents"), is_write=False)
        parents = ",".join(meta.get("parents", []))
        self._exec(
            self._drive.files().update(
                fileId=file_id,
                addParents=folder_id,
                removeParents=parents or None,
                fields="id, parents",
            ),
            is_write=True,
        )

    def _set_public_read(self) -> None:
        self._exec(
            self._drive.permissions().create(
                fileId=self._spreadsheet_id,
                body={"type": "anyone", "role": "reader"},
                fields="id",
            ),
            is_write=True,
        )

    def _share_to_email(self, email: str, *, role: str) -> None:
        self._exec(
            self._drive.permissions().create(
                fileId=self._spreadsheet_id,
                body={"type": "user", "role": role, "emailAddress": email},
                fields="id",
                sendNotificationEmail=False,
            ),
            is_write=True,
        )

    # ==================== schema ====================
    def ensure_schema(self) -> None:
        if self._ensured_schema:
            return

        # minimal schema：只保留“看板 + 币种查询子表”，不创建事实/元数据等 tab。
        if self._schema_mode == "minimal":
            self._refresh_sheet_map()
            if self._tab_dashboard not in self._sheet_id_by_title:
                self._exec(
                    self._sheets.spreadsheets().batchUpdate(
                        spreadsheetId=self._spreadsheet_id,
                        body={"requests": [{"addSheet": {"properties": {"title": self._tab_dashboard}}}]},
                    ),
                    is_write=True,
                )
                self._refresh_sheet_map()
            # 进程启动后尽量恢复 append cursor（避免 append 模式重启后从 1 覆盖）
            try:
                meta = self._local_meta_get()
                self._append_cursor_y = int(str(meta.get("dashboard_next_row") or "1").strip() or "1")
            except Exception:
                self._append_cursor_y = 1
            self._ensured_schema = True
            return

        wanted = [
            self._tab_dashboard,
            self._tab_cards_index,
            self._tab_card_fields_eav,
            self._tab_card_rows,
            self._tab_row_fields_eav,
            self._tab_blobs_index,
            self._tab_meta,
        ]
        self._refresh_sheet_map()

        # 兼容：旧工作簿若使用英文 tab 名，自动迁移为中文（保证“全部子表中文命名”）
        self._migrate_legacy_tabs()
        self._refresh_sheet_map()

        missing = [n for n in wanted if n not in self._sheet_id_by_title]
        if missing:
            reqs = [{"addSheet": {"properties": {"title": name}}} for name in missing]
            self._exec(
                self._sheets.spreadsheets().batchUpdate(
                    spreadsheetId=self._spreadsheet_id,
                    body={"requests": reqs},
                ),
                is_write=True,
            )
            self._refresh_sheet_map()

        # headers（dashboard 不需要，但保留一致性）
        self._ensure_header_row(
            self._tab_cards_index,
            [
                "card_key",
                "ts_utc",
                "source_service",
                "card_type",
                "title",
                "update_time",
                "sort_desc",
                "last_update",
                "tg_url",
                "dash_sheet",
                "dash_col_l",
                "dash_col_r",
                "dash_row_y",
                "dash_height",
            ],
        )
        self._ensure_header_row(self._tab_card_fields_eav, ["card_key", "field_path", "value_text", "value_type"])
        self._ensure_header_row(self._tab_card_rows, ["card_key", "row_index", "row_key", "row_json"])
        self._ensure_header_row(
            self._tab_row_fields_eav, ["card_key", "row_index", "field_path", "value_text", "value_type"]
        )
        self._ensure_header_row(
            self._tab_blobs_index, ["card_key", "blob_key", "sha256", "mime", "url", "size_chars", "created_at"]
        )
        self._ensure_header_row(self._tab_meta, ["key", "value"])

        # meta defaults
        meta = self._meta_get()
        defaults = {
            "schema_version": "1",
            "dashboard_next_row": str(meta.get("dashboard_next_row") or "1"),
            "dashboard_col_l": meta.get("dashboard_col_l") or self._dashboard_col_l,
            "dashboard_col_r": meta.get("dashboard_col_r") or self._dashboard_col_r,
            "dashboard_mode": meta.get("dashboard_mode") or self._dashboard_mode,
            "dashboard_slot_height": str(meta.get("dashboard_slot_height") or str(self._dashboard_slot_height)),
        }
        self._meta_set(defaults)

        self._ensured_schema = True

    # ==================== symbol tabs（币种查询子表） ====================
    def ensure_symbol_tab(self, *, title: str) -> None:
        self.ensure_schema()
        self._refresh_sheet_map()
        if title in self._sheet_id_by_title:
            return
        self._exec(
            self._sheets.spreadsheets().batchUpdate(
                spreadsheetId=self._spreadsheet_id,
                body={"requests": [{"addSheet": {"properties": {"title": title}}}]},
            ),
            is_write=True,
        )
        self._refresh_sheet_map()

    # ==================== generic sheet ops（用于变体看板） ====================
    def ensure_sheet(self, *, title: str) -> None:
        self.ensure_schema()
        self._refresh_sheet_map()
        if title in self._sheet_id_by_title:
            return
        self._exec(
            self._sheets.spreadsheets().batchUpdate(
                spreadsheetId=self._spreadsheet_id,
                body={"requests": [{"addSheet": {"properties": {"title": title}}}]},
            ),
            is_write=True,
        )
        self._refresh_sheet_map()

    def reset_sheet_display(self, *, title: str, col_l: str, col_r: str, compact: bool = True) -> dict[str, Any]:
        """
        清理指定 sheet 的展示面（用于“看板变体 tab”）：
        - clear values
        - unmerge all
        - clear formats（避免残留背景色/边框）
        - 可选：压缩 grid（仅影响该 sheet）
        """
        self.ensure_sheet(title=title)
        col_l_u = str(col_l).strip().upper()
        col_r_u = str(col_r).strip().upper()

        # 1) clear values
        self._exec(
            self._sheets.spreadsheets()
            .values()
            .clear(
                spreadsheetId=self._spreadsheet_id,
                range=f"{title}!A:ZZ",
            ),
            is_write=True,
        )

        sh_id = self._sheet_id_by_title.get(title)
        if sh_id is None:
            self._refresh_sheet_map()
            sh_id = self._sheet_id_by_title[title]

        # 2) unmerge all
        self._exec(
            self._sheets.spreadsheets().batchUpdate(
                spreadsheetId=self._spreadsheet_id,
                body={"requests": [{"unmergeCells": {"range": {"sheetId": int(sh_id)}}}]},
            ),
            is_write=True,
        )

        # 3) clear formats
        try:
            target_cols = max(_col_to_index(col_r_u), 1)
        except Exception:
            target_cols = 26
        target_rows = 2000 if compact else max(int(self._grid_by_title.get(title, (2000, 0))[0] or 2000), 1)
        self._exec(
            self._sheets.spreadsheets().batchUpdate(
                spreadsheetId=self._spreadsheet_id,
                body={
                    "requests": [
                        {
                            "repeatCell": {
                                "range": {
                                    "sheetId": int(sh_id),
                                    "startRowIndex": 0,
                                    "endRowIndex": int(target_rows),
                                    "startColumnIndex": 0,
                                    "endColumnIndex": int(target_cols),
                                },
                                "cell": {"userEnteredFormat": {}},
                                "fields": "userEnteredFormat",
                            }
                        }
                    ]
                },
            ),
            is_write=True,
        )

        if compact:
            target_rows = 2000
            target_cols = max(_col_to_index(col_r_u), 1)
            self._exec(
                self._sheets.spreadsheets().batchUpdate(
                    spreadsheetId=self._spreadsheet_id,
                    body={
                        "requests": [
                            {
                                "updateSheetProperties": {
                                    "properties": {
                                        "sheetId": int(sh_id),
                                        "gridProperties": {
                                            "rowCount": int(target_rows),
                                            "columnCount": int(target_cols),
                                            "frozenColumnCount": 0,
                                        },
                                    },
                                    "fields": "gridProperties.rowCount,gridProperties.columnCount,gridProperties.frozenColumnCount",
                                }
                            }
                        ]
                    },
                ),
                is_write=True,
            )
            self._refresh_sheet_map()

        return {"ok": True, "sheet": title, "col_l": col_l_u, "col_r": col_r_u}

    def write_symbol_query_tab(self, *, tab_title: str, sheet: Any) -> dict[str, Any]:
        """
        覆盖写“币种查询”子表（真表格）：
        - 每个值一个单元格（非“| 分隔符伪表格”）
        - 不做 append，避免 cells 无限增长
        - 通过 meta 记录上次 rows/cols，仅清理尾部差量，避免整表 clear 带来的闪烁
        - 支持样式版本升级（自动清除旧 conditional formatting，避免历史残留）
        """
        self.ensure_symbol_tab(title=tab_title)

        sh_id = self._sheet_id_by_title.get(tab_title)
        if sh_id is None:
            self._refresh_sheet_map()
            sh_id = self._sheet_id_by_title.get(tab_title)
        if sh_id is None:
            raise RuntimeError(f"missing_sheet:{tab_title}")

        values = getattr(sheet, "values", None) or []
        n_rows = int(getattr(sheet, "n_rows", 0) or len(values))
        n_cols = int(getattr(sheet, "n_cols", 0) or (len(values[0]) if values else 0))
        panel_title_rows = list(getattr(sheet, "panel_title_rows", []) or [])
        panel_header_rows = list(getattr(sheet, "panel_header_rows", []) or [])

        if not values or n_rows <= 0 or n_cols <= 0:
            values = [["-", "-", "-", "-", "-", "-", "-", "-", "-"]]
            n_rows, n_cols = 1, len(values[0])

        col_r = _index_to_col(n_cols)
        self._exec(
            self._sheets.spreadsheets()
            .values()
            .update(
                spreadsheetId=self._spreadsheet_id,
                range=f"{tab_title}!A1:{col_r}{n_rows}",
                valueInputOption="RAW",
                body={"values": values},
            ),
            is_write=True,
        )

        meta = self._meta_get()
        key_rows = f"symtab.{tab_title}.rows"
        key_cols = f"symtab.{tab_title}.cols"
        try:
            r_old = int(str(meta.get(key_rows) or "0").strip() or "0")
        except Exception:
            r_old = 0
        try:
            c_old = int(str(meta.get(key_cols) or "0").strip() or "0")
        except Exception:
            c_old = 0

        if r_old > n_rows:
            self._exec(
                self._sheets.spreadsheets()
                .values()
                .clear(
                    spreadsheetId=self._spreadsheet_id,
                    range=f"{tab_title}!A{n_rows + 1}:{_index_to_col(max(c_old, n_cols))}{r_old}",
                ),
                is_write=True,
            )
        if c_old > n_cols:
            self._exec(
                self._sheets.spreadsheets()
                .values()
                .clear(
                    spreadsheetId=self._spreadsheet_id,
                    range=f"{tab_title}!{_index_to_col(n_cols + 1)}1:{_index_to_col(c_old)}{max(r_old, n_rows)}",
                ),
                is_write=True,
            )

        # -------------------- style --------------------
        style_version = "symbol_table_v3"
        key_style_version = f"symtab.{tab_title}.style_version"
        key_style_rows = f"symtab.{tab_title}.style_rows"
        key_style_cols = f"symtab.{tab_title}.style_cols"
        try:
            styled_rows = int(str(meta.get(key_style_rows) or "0").strip() or "0")
        except Exception:
            styled_rows = 0
        try:
            styled_cols = int(str(meta.get(key_style_cols) or "0").strip() or "0")
        except Exception:
            styled_cols = 0

        target_rows = int(max(n_rows, styled_rows, 800))
        target_cols = int(max(n_cols, styled_cols, 9))
        need_style = (
            (meta.get(key_style_version) or "") != style_version
            or target_rows > styled_rows
            or target_cols != styled_cols
        )
        if need_style:
            self._ensure_grid_size(tab_title, min_rows=target_rows, min_cols=target_cols)

            # 清除旧 conditional formatting（避免历史规则残留）
            try:
                ss = self._exec(
                    self._sheets.spreadsheets().get(
                        spreadsheetId=self._spreadsheet_id,
                        fields="sheets(properties(sheetId,title),conditionalFormats)",
                    ),
                    is_write=False,
                )
                cond_cnt = 0
                for sh in ss.get("sheets", []):
                    props = sh.get("properties") or {}
                    if int(props.get("sheetId") or 0) != int(sh_id):
                        continue
                    cond = sh.get("conditionalFormats") or []
                    cond_cnt = len(cond)
                    break
                if cond_cnt > 0:
                    reqs = [
                        {"deleteConditionalFormatRule": {"sheetId": int(sh_id), "index": 0}} for _ in range(cond_cnt)
                    ]
                    self._exec(
                        self._sheets.spreadsheets().batchUpdate(
                            spreadsheetId=self._spreadsheet_id,
                            body={"requests": reqs},
                        ),
                        is_write=True,
                    )
            except Exception:
                pass

            reqs: list[dict[str, Any]] = []

            reqs.append(
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": int(sh_id),
                            "startRowIndex": 0,
                            "endRowIndex": int(target_rows),
                            "startColumnIndex": 0,
                            "endColumnIndex": int(target_cols),
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": _rgb(1.0, 1.0, 1.0),
                                "textFormat": {
                                    "fontFamily": "Arial",
                                    "fontSize": 10,
                                    "foregroundColor": _rgb(0.1, 0.1, 0.1),
                                },
                                "horizontalAlignment": "LEFT",
                                "verticalAlignment": "MIDDLE",
                                "wrapStrategy": "WRAP",
                            }
                        },
                        "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment,wrapStrategy)",
                    }
                }
            )

            # widths：A,B wider；periods fixed
            reqs.append(
                {
                    "updateDimensionProperties": {
                        "range": {"sheetId": int(sh_id), "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1},
                        "properties": {"pixelSize": 200},
                        "fields": "pixelSize",
                    }
                }
            )
            reqs.append(
                {
                    "updateDimensionProperties": {
                        "range": {"sheetId": int(sh_id), "dimension": "COLUMNS", "startIndex": 1, "endIndex": 2},
                        "properties": {"pixelSize": 220},
                        "fields": "pixelSize",
                    }
                }
            )

            raw_block_start_col_0 = getattr(sheet, "raw_block_start_col_0", None)
            try:
                raw_block_start_col_0 = int(raw_block_start_col_0) if raw_block_start_col_0 is not None else None
            except Exception:
                raw_block_start_col_0 = None

            # columns >= C：默认 90；若存在 raw 镜像区，则 display/raw 区域分别设置宽度并可隐藏
            for ci in range(2, int(target_cols)):
                px = 90
                if raw_block_start_col_0 is not None and 0 <= raw_block_start_col_0 < int(n_cols):
                    if ci == int(raw_block_start_col_0):
                        px = 26  # 分隔列
                    elif int(raw_block_start_col_0) < ci < int(n_cols):
                        px = 80  # raw 周期列
                reqs.append(
                    {
                        "updateDimensionProperties": {
                            "range": {
                                "sheetId": int(sh_id),
                                "dimension": "COLUMNS",
                                "startIndex": ci,
                                "endIndex": ci + 1,
                            },
                            "properties": {"pixelSize": int(px)},
                            "fields": "pixelSize",
                        }
                    }
                )

            # 周期列右对齐
            if target_cols > 2:
                reqs.append(
                    {
                        "repeatCell": {
                            "range": {
                                "sheetId": int(sh_id),
                                "startRowIndex": 0,
                                "endRowIndex": int(target_rows),
                                "startColumnIndex": 2,
                                "endColumnIndex": int(target_cols),
                            },
                            "cell": {"userEnteredFormat": {"horizontalAlignment": "RIGHT", "wrapStrategy": "CLIP"}},
                            "fields": "userEnteredFormat(horizontalAlignment,wrapStrategy)",
                        }
                    }
                )

            # raw 镜像区：浅灰底 + 可隐藏（默认隐藏）
            if raw_block_start_col_0 is not None and 0 <= raw_block_start_col_0 < int(n_cols):
                raw_sep = int(raw_block_start_col_0)
                raw_end = int(n_cols)

                # separator column subtle bg
                reqs.append(
                    {
                        "repeatCell": {
                            "range": {
                                "sheetId": int(sh_id),
                                "startRowIndex": 0,
                                "endRowIndex": int(target_rows),
                                "startColumnIndex": raw_sep,
                                "endColumnIndex": raw_sep + 1,
                            },
                            "cell": {"userEnteredFormat": {"backgroundColor": _rgb(0.97, 0.97, 0.97)}},
                            "fields": "userEnteredFormat(backgroundColor)",
                        }
                    }
                )

                # raw columns bg
                if raw_end > raw_sep + 1:
                    reqs.append(
                        {
                            "repeatCell": {
                                "range": {
                                    "sheetId": int(sh_id),
                                    "startRowIndex": 0,
                                    "endRowIndex": int(target_rows),
                                    "startColumnIndex": raw_sep + 1,
                                    "endColumnIndex": raw_end,
                                },
                                "cell": {"userEnteredFormat": {"backgroundColor": _rgb(0.985, 0.985, 0.99)}},
                                "fields": "userEnteredFormat(backgroundColor)",
                            }
                        }
                    )

                raw_mode = (os.environ.get("SHEETS_SYMBOL_QUERY_RAW_MODE", "hidden") or "hidden").strip().lower()
                if raw_mode not in {"hidden", "show", "off"}:
                    raw_mode = "hidden"
                if raw_mode != "off":
                    reqs.append(
                        {
                            "updateDimensionProperties": {
                                "range": {
                                    "sheetId": int(sh_id),
                                    "dimension": "COLUMNS",
                                    "startIndex": raw_sep,
                                    "endIndex": raw_end,
                                },
                                "properties": {"hiddenByUser": raw_mode == "hidden"},
                                "fields": "hiddenByUser",
                            }
                        }
                    )

            # freeze top info rows
            reqs.append(
                {
                    "updateSheetProperties": {
                        "properties": {
                            "sheetId": int(sh_id),
                            "gridProperties": {"frozenRowCount": 3, "frozenColumnCount": 2},
                        },
                        "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount",
                    }
                }
            )

            # top info row emphasis
            reqs.append(
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": int(sh_id),
                            "startRowIndex": 0,
                            "endRowIndex": 1,
                            "startColumnIndex": 0,
                            "endColumnIndex": int(target_cols),
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": _rgb(0.13, 0.15, 0.18),
                                "textFormat": {"bold": True, "foregroundColor": _rgb(1.0, 1.0, 1.0)},
                            }
                        },
                        "fields": "userEnteredFormat(backgroundColor,textFormat.bold,textFormat.foregroundColor)",
                    }
                }
            )

            # panel title rows
            for r in panel_title_rows:
                rr0 = max(int(r) - 1, 0)
                reqs.append(
                    {
                        "repeatCell": {
                            "range": {
                                "sheetId": int(sh_id),
                                "startRowIndex": rr0,
                                "endRowIndex": rr0 + 1,
                                "startColumnIndex": 0,
                                "endColumnIndex": int(target_cols),
                            },
                            "cell": {
                                "userEnteredFormat": {
                                    "backgroundColor": _rgb(0.10, 0.45, 0.82),
                                    "textFormat": {"bold": True, "foregroundColor": _rgb(1.0, 1.0, 1.0)},
                                }
                            },
                            "fields": "userEnteredFormat(backgroundColor,textFormat.bold,textFormat.foregroundColor)",
                        }
                    }
                )

            # panel header rows
            for r in panel_header_rows:
                rr0 = max(int(r) - 1, 0)
                reqs.append(
                    {
                        "repeatCell": {
                            "range": {
                                "sheetId": int(sh_id),
                                "startRowIndex": rr0,
                                "endRowIndex": rr0 + 1,
                                "startColumnIndex": 0,
                                "endColumnIndex": int(target_cols),
                            },
                            "cell": {
                                "userEnteredFormat": {
                                    "backgroundColor": _rgb(0.93, 0.94, 0.96),
                                    "textFormat": {"bold": True},
                                }
                            },
                            "fields": "userEnteredFormat(backgroundColor,textFormat.bold)",
                        }
                    }
                )

            self._exec(
                self._sheets.spreadsheets().batchUpdate(
                    spreadsheetId=self._spreadsheet_id,
                    body={"requests": reqs},
                ),
                is_write=True,
            )
            self._meta_set(
                {
                    key_style_version: style_version,
                    key_style_rows: str(target_rows),
                    key_style_cols: str(target_cols),
                }
            )

        self._meta_set({key_rows: str(n_rows), key_cols: str(n_cols)})
        return {"ok": True, "tab": tab_title, "rows": n_rows, "cols": n_cols}

    def write_symbol_txt_tab(self, *, tab_title: str, text: str) -> dict[str, Any]:
        raise RuntimeError("币种查询子表已升级为真表格：请改用 write_symbol_query_tab(tab_title=..., sheet=...)")

    # ==================== dashboard variants ====================
    def _render_dashboard_to_sheet(
        self, payload: dict[str, Any], *, sheet_title: str, y: int, col_l: str, col_r: str
    ) -> None:
        """
        与 `_render_dashboard` 同口径渲染，但写入到指定 sheet（用于“看板变体 tab”）。
        说明：
        - 仍保留：字段组/周期两行表头、周期灰白交替、字段组竖线、源信息行整行合并
        - 该函数只负责渲染，不负责 slot/meta
        """
        col_l_idx = _col_to_index(col_l)
        col_r_idx = _col_to_index(col_r)
        width = col_r_idx - col_l_idx + 1
        if width <= 0:
            raise RuntimeError("invalid_dashboard_col_range")

        header = payload.get("header") or {}
        hint = payload.get("hint") or {}
        params = payload.get("params") or {}
        table = payload.get("table") or {}
        columns = table.get("columns") or []
        rows = table.get("rows") or []

        title = str(header.get("title") or "")
        update_time = str(header.get("update_time") or "-").strip() or "-"
        sort_desc = str(header.get("sort_desc") or "-").strip() or "-"
        hint_text = str(hint.get("text") or "-").strip() or "-"
        last_update = str(params.get("last_update") or "-").strip() or "-"

        info_line = " ".join(
            [
                f"📊 {title or '-'}",
                f"⏰ 更新 {update_time}",
                f"📊 排序 {sort_desc}",
                f"💡 {hint_text}",
                f"⏰ 最后更新 {last_update}",
            ]
        )

        def pad_row(first: str) -> list[str]:
            return [first] + [""] * (width - 1)

        value_rows: list[tuple[str, list[list[str]]]] = []
        value_rows.append((f"{sheet_title}!{col_l}{y}:{col_r}{y}", [pad_row(info_line)]))

        chunks = [columns[i : i + width] for i in range(0, len(columns), width)] if columns else [[]]

        table_y = y + 1
        for chunk_cols in chunks:
            group_row = [_parse_field_group(str(c)) for c in chunk_cols]
            period_row = [_parse_period_suffix(str(c)) for c in chunk_cols]
            group_row = group_row + [""] * (width - len(group_row))
            period_row = period_row + [""] * (width - len(period_row))
            value_rows.append((f"{sheet_title}!{col_l}{table_y}:{col_r}{table_y}", [group_row]))
            value_rows.append((f"{sheet_title}!{col_l}{table_y + 1}:{col_r}{table_y + 1}", [period_row]))

            if rows:
                body_vals: list[list[str]] = []
                for r in rows:
                    line: list[str] = []
                    for c in chunk_cols:
                        line.append("" if r.get(c) is None else str(r.get(c)))
                    line = line + [""] * (width - len(line))
                    body_vals.append(line)
                y0 = table_y + 2
                y1 = table_y + 1 + len(body_vals)
                value_rows.append((f"{sheet_title}!{col_l}{y0}:{col_r}{y1}", body_vals))

            table_y += 2 + len(rows)

        data = [{"range": rng, "values": vals} for rng, vals in value_rows]
        self._exec(
            self._sheets.spreadsheets()
            .values()
            .batchUpdate(
                spreadsheetId=self._spreadsheet_id,
                body={"valueInputOption": "RAW", "data": data},
            ),
            is_write=True,
        )

        sh_id = self._sheet_id_by_title.get(sheet_title)
        if sh_id is None:
            self._refresh_sheet_map()
            sh_id = self._sheet_id_by_title[sheet_title]

        col_l0 = col_l_idx - 1
        col_r1 = col_r_idx

        def rrange(*, r0: int, r1: int, c0: int, c1: int) -> dict[str, Any]:
            return {
                "sheetId": int(sh_id),
                "startRowIndex": int(r0),
                "endRowIndex": int(r1),
                "startColumnIndex": int(c0),
                "endColumnIndex": int(c1),
            }

        bg_hdr_info = _rgb(0.13, 0.15, 0.18)
        bg_hdr_group = _rgb(0.86, 0.90, 0.96)
        bg_hdr_period = _rgb(0.93, 0.94, 0.96)
        bg_body_even = _rgb(1.0, 1.0, 1.0)
        bg_body_odd = _rgb(0.97, 0.97, 0.97)

        requests: list[dict[str, Any]] = []

        # 源信息行：背景/字体
        requests.append(
            {
                "repeatCell": {
                    "range": rrange(r0=y - 1, r1=y, c0=col_l0, c1=col_r1),
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": bg_hdr_info,
                            "textFormat": {"bold": True, "foregroundColor": _rgb(1.0, 1.0, 1.0)},
                            "wrapStrategy": "WRAP",
                        }
                    },
                    "fields": "userEnteredFormat(backgroundColor,textFormat.bold,textFormat.foregroundColor,wrapStrategy)",
                }
            }
        )

        # 每个 chunk 的 header/body 样式
        table_y = y + 1
        for chunk_cols in chunks:
            # header 字体加粗
            requests.append(
                {
                    "repeatCell": {
                        "range": rrange(r0=table_y - 1, r1=table_y + 1, c0=col_l0, c1=col_r1),
                        "cell": {
                            "userEnteredFormat": {
                                "textFormat": {"bold": True},
                                "horizontalAlignment": "CENTER",
                                "verticalAlignment": "MIDDLE",
                                "wrapStrategy": "WRAP",
                            }
                        },
                        "fields": "userEnteredFormat(textFormat.bold,horizontalAlignment,verticalAlignment,wrapStrategy)",
                    }
                }
            )

            period_index: dict[str, int] = {}
            period_by_col: list[str] = []
            for c in chunk_cols + [""] * (width - len(chunk_cols)):
                suf = _parse_period_suffix(str(c))
                if suf and suf not in period_index:
                    period_index[suf] = len(period_index)
                period_by_col.append(suf)

            def col_bg(suf: str, *, _period_index: dict[str, int] = period_index) -> dict[str, float]:
                if not suf:
                    return bg_body_odd
                idx = int(_period_index.get(suf, 0))
                return bg_body_even if idx % 2 == 0 else bg_body_odd

            body_bgs = [col_bg(suf) for suf in period_by_col]

            def add_bg_segments(*, row0: int, row1: int, bgs: list[dict[str, float]]) -> None:
                start = 0
                while start < width:
                    bg = bgs[start]
                    end = start + 1
                    while end < width and bgs[end] == bg:
                        end += 1
                    requests.append(
                        {
                            "repeatCell": {
                                "range": rrange(r0=row0, r1=row1, c0=col_l0 + start, c1=col_l0 + end),
                                "cell": {"userEnteredFormat": {"backgroundColor": bg}},
                                "fields": "userEnteredFormat.backgroundColor",
                            }
                        }
                    )
                    start = end

            def add_field_group_separators(*, row0: int, row1: int, _cols: list[str] = chunk_cols) -> None:
                sep_color = _rgb(0.70, 0.70, 0.70)
                border = {"style": "SOLID_MEDIUM", "width": 2, "color": sep_color}
                last_group = ""
                for idx, c in enumerate(list(_cols) + [""] * (width - len(_cols))):
                    g = _parse_field_group(str(c))
                    if not g:
                        continue
                    if last_group and g != last_group:
                        requests.append(
                            {
                                "updateBorders": {
                                    "range": rrange(r0=row0, r1=row1, c0=col_l0 + idx, c1=col_l0 + idx + 1),
                                    "left": border,
                                }
                            }
                        )
                    last_group = g

            # header 背景（两行）
            requests.append(
                {
                    "repeatCell": {
                        "range": rrange(r0=table_y - 1, r1=table_y, c0=col_l0, c1=col_r1),
                        "cell": {"userEnteredFormat": {"backgroundColor": bg_hdr_group}},
                        "fields": "userEnteredFormat.backgroundColor",
                    }
                }
            )
            requests.append(
                {
                    "repeatCell": {
                        "range": rrange(r0=table_y, r1=table_y + 1, c0=col_l0, c1=col_r1),
                        "cell": {"userEnteredFormat": {"backgroundColor": bg_hdr_period}},
                        "fields": "userEnteredFormat.backgroundColor",
                    }
                }
            )
            if rows:
                body_r0 = table_y + 1
                body_r1 = table_y + 1 + len(rows)
                add_bg_segments(row0=body_r0, row1=body_r1, bgs=body_bgs)
                add_field_group_separators(row0=table_y - 1, row1=body_r1)

            # 字段组表头 merge
            group_names = [_parse_field_group(str(c)) for c in chunk_cols] + [""] * (width - len(chunk_cols))
            start = 0
            while start < width:
                g = group_names[start]
                end = start + 1
                while end < width and group_names[end] == g:
                    end += 1
                if g and end - start >= 2:
                    requests.append(
                        {
                            "mergeCells": {
                                "range": rrange(r0=table_y - 1, r1=table_y, c0=col_l0 + start, c1=col_l0 + end),
                                "mergeType": "MERGE_ALL",
                            }
                        }
                    )
                start = end

            table_y += 2 + len(rows)

        # info 行合并（整行）
        requests.append(
            {
                "mergeCells": {
                    "range": {
                        "sheetId": int(sh_id),
                        "startRowIndex": y - 1,
                        "endRowIndex": y,
                        "startColumnIndex": col_l_idx - 1,
                        "endColumnIndex": col_r_idx,
                    },
                    "mergeType": "MERGE_ALL",
                }
            }
        )

        self._exec(
            self._sheets.spreadsheets().batchUpdate(
                spreadsheetId=self._spreadsheet_id,
                body={"requests": requests},
            ),
            is_write=True,
        )

    def write_dashboard_variants(self, *, payloads: list[dict[str, Any]], col_l: str, min_col_r: str) -> dict[str, Any]:
        """
        生成 3 套“单面板高密度”看板变体（各自独立 tab，便于对比后择优）：
        - 方案1：单元格内多周期（最窄，0 交互）
        - 方案2：紧凑 + 原始展开（同一 tab 内上下两段；原始段浅灰）
        - 方案3：纵向多周期（真表格，可排序/筛选，0 交互但更长）
        - 方案4：纵向多周期 + 合并币种单元格（每个币种 7 行周期，币种列纵向 merge）
        """
        variants = [
            ("看板_方案1_单元格多周期", "v1"),
            ("看板_方案2_紧凑+详情", "v2"),
            ("看板_方案3_纵向多周期", "v3"),
            ("看板_方案4_纵向合并币种", "v4"),
        ]

        # 允许只生成指定方案，避免写入配额爆炸
        # - SHEETS_DASHBOARD_VARIANTS=1,2,4 或 v1,v2,v4
        sel_raw = (os.environ.get("SHEETS_DASHBOARD_VARIANTS", "") or "").strip()
        if sel_raw:
            want: set[str] = set()
            for it in sel_raw.split(","):
                s = it.strip().lower()
                if not s:
                    continue
                if s in {"1", "2", "3", "4"}:
                    want.add(f"v{s}")
                elif s.startswith("v") and s[1:] in {"1", "2", "3", "4"}:
                    want.add(f"v{s[1:]}")
            if want:
                variants = [(t, m) for (t, m) in variants if m in want]

        results: dict[str, Any] = {"ok": True, "variants": []}
        for title, mode in variants:
            # 变体 tab 用更窄的 col_r（按实际列数计算），但不小于 min_col_r
            max_cols = 1
            transformed: list[dict[str, Any]] = []
            for p in payloads:
                table = p.get("table") or {}
                cols = table.get("columns") or []
                rows = table.get("rows") or []
                if not isinstance(cols, list) or not isinstance(rows, list):
                    transformed.append(p)
                    continue

                cols_s = [str(c) for c in cols if c is not None]
                if mode == "v1":
                    vt: VariantTable = compact_cell_multiperiod(columns=cols_s, rows=rows)
                    np = dict(p)
                    np["table"] = {"columns": vt.columns, "rows": vt.rows}
                    transformed.append(np)
                    max_cols = max(max_cols, len(vt.columns))
                elif mode in {"v3", "v4"}:
                    vt = vertical_multiperiod(columns=cols_s, rows=rows)
                    np = dict(p)
                    np["table"] = {"columns": vt.columns, "rows": vt.rows}
                    transformed.append(np)
                    max_cols = max(max_cols, len(vt.columns))
                else:
                    # v2：保留原始表（第二段），紧凑表（第一段）
                    vt = compact_cell_multiperiod(columns=cols_s, rows=rows)
                    np = dict(p)
                    np["table"] = {"columns": vt.columns, "rows": vt.rows}
                    # 原始表放到 params（只用于本次渲染，不落事实表）
                    prm = dict(np.get("params") or {}) if isinstance(np.get("params"), dict) else {}
                    prm["_variant_raw_table"] = {"columns": cols_s, "rows": rows}
                    np["params"] = prm
                    transformed.append(np)
                    max_cols = max(max_cols, len(vt.columns), len(cols_s))

            col_r = self.compute_col_r(col_l=col_l, needed_cols=max_cols, min_col_r=min_col_r)
            self.reset_sheet_display(title=title, col_l=col_l, col_r=col_r, compact=True)

            y = 1
            for p in transformed:
                # v2：先渲染紧凑表，再渲染原始展开表（浅灰标题）
                if mode == "v2":
                    raw_tbl = None
                    prm = p.get("params") or {}
                    if isinstance(prm, dict):
                        raw_tbl = prm.get("_variant_raw_table")
                    height = self._calc_dashboard_height(p, col_l=col_l, col_r=col_r)
                    self._ensure_grid_size(title, min_rows=y + height, min_cols=_col_to_index(col_r))
                    self._render_dashboard_to_sheet(p, sheet_title=title, y=y, col_l=col_l, col_r=col_r)
                    y += height

                    if isinstance(raw_tbl, dict):
                        # 详情段：复用同一 header，但 title 加前缀，避免误解为另一张卡
                        pp = dict(p)
                        hdr = dict(pp.get("header") or {}) if isinstance(pp.get("header"), dict) else {}
                        hdr["title"] = f"🔎 详情（原始展开） {str(hdr.get('title') or '').replace('📊', '').strip()}"
                        pp["header"] = hdr
                        pp["table"] = {
                            "columns": list(raw_tbl.get("columns") or []),
                            "rows": list(raw_tbl.get("rows") or []),
                        }
                        height2 = self._calc_dashboard_height(pp, col_l=col_l, col_r=col_r)
                        self._ensure_grid_size(title, min_rows=y + height2, min_cols=_col_to_index(col_r))
                        self._render_dashboard_to_sheet(pp, sheet_title=title, y=y, col_l=col_l, col_r=col_r)
                        y += height2
                    continue

                height = self._calc_dashboard_height(p, col_l=col_l, col_r=col_r)
                self._ensure_grid_size(title, min_rows=y + height, min_cols=_col_to_index(col_r))
                self._render_dashboard_to_sheet(p, sheet_title=title, y=y, col_l=col_l, col_r=col_r)

                # v4：对“纵向多周期表”的币种列做纵向合并（每个币种通常对应 7 行周期）
                if mode == "v4":
                    try:
                        table = p.get("table") or {}
                        cols = table.get("columns") or []
                        rows = table.get("rows") or []
                        if isinstance(cols, list) and isinstance(rows, list) and cols:
                            sym_col = str(cols[0] or "").strip() or "币种"
                            # body 第 1 行：y(info) + 2(header rows) + 1
                            body_start_row_1 = int(y) + 3
                            self._merge_symbol_column_groups_on_sheet(
                                sheet_title=title,
                                col_l=col_l,
                                sym_col=sym_col,
                                body_start_row_1=body_start_row_1,
                                body_rows=rows,
                            )
                    except Exception:
                        pass

                y += height

            results["variants"].append({"sheet": title, "mode": mode, "col_r": col_r, "cards": len(transformed)})

        return results

    def _merge_symbol_column_groups_on_sheet(
        self,
        *,
        sheet_title: str,
        col_l: str,
        sym_col: str,
        body_start_row_1: int,
        body_rows: list[dict[str, Any]],
    ) -> None:
        """
        将同一币种的连续行在“币种列”纵向合并，提升纵向多周期表的可读性。
        - 只合并 body（不动 header）
        - 只合并连续相同值（不强依赖 7 行/币种的假设）
        """
        if not body_rows:
            return

        sh_id = self._sheet_id_by_title.get(sheet_title)
        if sh_id is None:
            self._refresh_sheet_map()
            sh_id = self._sheet_id_by_title.get(sheet_title)
        if sh_id is None:
            return

        col_l_idx = _col_to_index(col_l)
        sym_col_idx0 = col_l_idx - 1  # 币种列在该变体中固定为第一列（A 起始）

        def val_at(i: int) -> str:
            try:
                r = body_rows[i]
                v = r.get(sym_col)
                return "" if v is None else str(v).strip()
            except Exception:
                return ""

        requests: list[dict[str, Any]] = []
        i = 0
        while i < len(body_rows):
            v0 = val_at(i)
            j = i + 1
            while j < len(body_rows) and val_at(j) == v0:
                j += 1
            span = j - i
            if v0 and span >= 2:
                r0 = (body_start_row_1 + i) - 1
                r1 = (body_start_row_1 + j) - 1
                requests.append(
                    {
                        "mergeCells": {
                            "range": {
                                "sheetId": int(sh_id),
                                "startRowIndex": int(r0),
                                "endRowIndex": int(r1),
                                "startColumnIndex": int(sym_col_idx0),
                                "endColumnIndex": int(sym_col_idx0 + 1),
                            },
                            "mergeType": "MERGE_ALL",
                        }
                    }
                )
                # 合并后居中（更像“分组标题”）
                requests.append(
                    {
                        "repeatCell": {
                            "range": {
                                "sheetId": int(sh_id),
                                "startRowIndex": int(r0),
                                "endRowIndex": int(r1),
                                "startColumnIndex": int(sym_col_idx0),
                                "endColumnIndex": int(sym_col_idx0 + 1),
                            },
                            "cell": {
                                "userEnteredFormat": {
                                    "horizontalAlignment": "CENTER",
                                    "verticalAlignment": "MIDDLE",
                                    "textFormat": {"bold": True},
                                }
                            },
                            "fields": "userEnteredFormat(horizontalAlignment,verticalAlignment,textFormat.bold)",
                        }
                    }
                )
            i = j

        if not requests:
            return

        self._exec(
            self._sheets.spreadsheets().batchUpdate(
                spreadsheetId=self._spreadsheet_id,
                body={"requests": requests},
            ),
            is_write=True,
        )

    # ==================== ops ====================
    def reset_dashboard(self, *, col_l: str, col_r: str, compact: bool = False) -> dict[str, Any]:
        """
        清理看板展示面（不动事实表）：
        - 清空看板全部单元格
        - 解除全部合并单元格
        - 重置 meta.dashboard_next_row=1，并写入新的 dashboard_col_l/dashboard_col_r
        - 清空 slot.*.y（避免“重置后仍沿用旧卡片 y”造成看起来像堆叠/错位）
        """
        self.ensure_schema()
        col_l_u = str(col_l).strip().upper()
        col_r_u = str(col_r).strip().upper()
        self._dashboard_col_l = col_l_u
        self._dashboard_col_r = col_r_u
        self._append_cursor_y = 1

        # 1) clear values
        self._exec(
            self._sheets.spreadsheets()
            .values()
            .clear(
                spreadsheetId=self._spreadsheet_id,
                range=f"{self._tab_dashboard}!A:ZZ",
            ),
            is_write=True,
        )

        # 2) unmerge all
        sh_id = self._sheet_id_by_title.get(self._tab_dashboard)
        if sh_id is None:
            self._refresh_sheet_map()
            sh_id = self._sheet_id_by_title[self._tab_dashboard]

        self._exec(
            self._sheets.spreadsheets().batchUpdate(
                spreadsheetId=self._spreadsheet_id,
                body={"requests": [{"unmergeCells": {"range": {"sheetId": int(sh_id)}}}]},
            ),
            is_write=True,
        )

        # 2.5) clear formats/borders（避免“残留配色/残留竖线”）
        # values.clear 不会清掉 userEnteredFormat；必须显式重置。
        try:
            target_cols = max(_col_to_index(col_r_u), 1)
        except Exception:
            target_cols = 26
        target_rows = (
            2000 if compact else max(int(self._grid_by_title.get(self._tab_dashboard, (2000, 0))[0] or 2000), 1)
        )
        self._exec(
            self._sheets.spreadsheets().batchUpdate(
                spreadsheetId=self._spreadsheet_id,
                body={
                    "requests": [
                        {
                            "repeatCell": {
                                "range": {
                                    "sheetId": int(sh_id),
                                    "startRowIndex": 0,
                                    "endRowIndex": int(target_rows),
                                    "startColumnIndex": 0,
                                    "endColumnIndex": int(target_cols),
                                },
                                "cell": {"userEnteredFormat": {}},
                                "fields": "userEnteredFormat",
                            }
                        }
                    ]
                },
            ),
            is_write=True,
        )

        # 3) reset meta
        if self._schema_mode == "minimal":
            # local meta：只清理 dashboard 与 slot，避免无意义增长
            self._local_meta_set(
                {
                    "dashboard_next_row": "1",
                    "dashboard_col_l": col_l_u,
                    "dashboard_col_r": col_r_u,
                    "dashboard_mode": self._dashboard_mode,
                    "dashboard_slot_height": str(self._dashboard_slot_height),
                },
                clear_prefixes=["slot."],
            )
        else:
            meta = self._meta_get()
            slot_clear: dict[str, str] = {}
            for k in meta.keys():
                if k.startswith("slot.") and (k.endswith(".y") or k.endswith(".h")):
                    slot_clear[k] = "0"

            kv = {
                "dashboard_next_row": "1",
                "dashboard_col_l": col_l_u,
                "dashboard_col_r": col_r_u,
                "dashboard_mode": self._dashboard_mode,
                "dashboard_slot_height": str(self._dashboard_slot_height),
                **slot_clear,
            }
            self._meta_set(kv)

        if compact:
            # 只压缩 dashboard 本身（展示面允许破坏性变更），避免历史事实表被误删。
            sh_id = self._sheet_id_by_title.get(self._tab_dashboard)
            if sh_id is None:
                self._refresh_sheet_map()
                sh_id = self._sheet_id_by_title[self._tab_dashboard]

            target_rows = 2000
            target_cols = max(_col_to_index(col_r_u), 1)
            self._exec(
                self._sheets.spreadsheets().batchUpdate(
                    spreadsheetId=self._spreadsheet_id,
                    body={
                        "requests": [
                            {
                                "updateSheetProperties": {
                                    "properties": {
                                        "sheetId": int(sh_id),
                                        "gridProperties": {
                                            "rowCount": int(target_rows),
                                            "columnCount": int(target_cols),
                                            # 看板会大量 mergeCells（title/update/sort/hint/last 全行合并）；
                                            # Sheets 禁止跨“冻结列边界”合并，因此这里强制关闭冻结列。
                                            "frozenColumnCount": 0,
                                        },
                                    },
                                    "fields": "gridProperties.rowCount,gridProperties.columnCount,gridProperties.frozenColumnCount",
                                }
                            }
                        ]
                    },
                ),
                is_write=True,
            )
            self._refresh_sheet_map()
        return {"ok": True, "dashboard": {"sheet": self._tab_dashboard, "col_l": col_l, "col_r": col_r, "row_y": 1}}

    def rebuild_dashboard(self, *, max_cards: int = 200) -> dict[str, Any]:
        """
        从事实表重建看板（用于运维：看板可随时重建）。

        读取来源：
        - cards_index：卡片索引（按 append 顺序，取最后 max_cards）
        - card_fields_eav：提取 hint.text / table.columns[*]
        - card_rows：row_json 还原 table.rows
        """
        self.ensure_schema()
        if self._schema_mode == "minimal":
            raise RuntimeError(
                "minimal_schema 下不支持从事实表重建：请先切回 SHEETS_SCHEMA_MODE=full 或关闭 --rebuild-dashboard"
            )

        meta = self._meta_get()
        col_l = (meta.get("dashboard_col_l") or self._dashboard_col_l).strip().upper()
        col_r = (meta.get("dashboard_col_r") or self._dashboard_col_r).strip().upper()
        mode = (self._dashboard_mode or meta.get("dashboard_mode") or "replace").strip().lower()
        if mode not in {"append", "replace"}:
            mode = "replace"

        # 1) 拉取索引
        idx_vals = self._exec(
            self._sheets.spreadsheets()
            .values()
            .get(
                spreadsheetId=self._spreadsheet_id,
                range=f"{self._tab_cards_index}!A:N",
            ),
            is_write=False,
        ).get("values", [])
        if not idx_vals or len(idx_vals) <= 1:
            self.reset_dashboard(col_l=col_l, col_r=col_r)
            return {"ok": True, "cards": 0, "note": "cards_index 为空"}

        rows = idx_vals[1:]

        # 取最后 N 条
        if max_cards > 0:
            rows = rows[-max_cards:]

        # 索引列（按 ensure_schema 的表头）
        # card_key, ts_utc, source_service, card_type, title, update_time, sort_desc, last_update, tg_url, ...
        def g(r: list[str], i: int) -> str:
            return str(r[i]).strip() if i < len(r) and r[i] is not None else ""

        # replace 模式：按 card_type 取“最新一条”，避免重建时把历史卡片按时间堆叠出一长串。
        picked_rows: list[list[str]] = []
        if mode == "replace":
            latest_by_type: dict[str, list[str]] = {}
            for r in rows:
                ck = g(r, 0)
                ct = g(r, 3)
                if not ck or not ct:
                    continue
                latest_by_type[ct] = r
            # 排序口径：优先按 TG 卡片 priority（越大越靠前），其次按 card_type 稳定排序。
            pri = self._load_card_priority_map()
            for ct in sorted(latest_by_type.keys(), key=lambda k: (-int(pri.get(k, 0) or 0), k)):
                picked_rows.append(latest_by_type[ct])
        else:
            picked_rows = rows

        card_items: list[dict[str, str]] = []
        wanted_keys: list[str] = []
        for r in picked_rows:
            ck = g(r, 0)
            if not ck:
                continue
            wanted_keys.append(ck)
            card_items.append(
                {
                    "card_key": ck,
                    "ts_utc": g(r, 1),
                    "source_service": g(r, 2),
                    "card_type": g(r, 3),
                    "title": g(r, 4),
                    "update_time": g(r, 5),
                    "sort_desc": g(r, 6),
                    "last_update": g(r, 7),
                    "tg_url": g(r, 8),
                }
            )

        wanted = set(wanted_keys)
        if not wanted:
            self.reset_dashboard(col_l=col_l, col_r=col_r)
            return {"ok": True, "cards": 0, "note": "no_valid_card_keys"}

        # 2) 拉取 EAV（只解析必要字段）
        eav_vals = self._exec(
            self._sheets.spreadsheets()
            .values()
            .get(
                spreadsheetId=self._spreadsheet_id,
                range=f"{self._tab_card_fields_eav}!A:D",
            ),
            is_write=False,
        ).get("values", [])
        # skip header
        eav_rows = eav_vals[1:] if eav_vals else []

        hint_by_key: dict[str, str] = {}
        cols_by_key: dict[str, dict[int, str]] = {}
        for r in eav_rows:
            if not r or len(r) < 4:
                continue
            ck = str(r[0]).strip()
            if ck not in wanted:
                continue
            path = str(r[1]).strip()
            vtext = "" if r[2] is None else str(r[2])

            if path == "hint.text":
                hint_by_key[ck] = vtext
                continue

            if path.startswith("table.columns[") and path.endswith("]"):
                try:
                    idx = int(path[len("table.columns[") : -1])
                except Exception:
                    continue
                cols_by_key.setdefault(ck, {})[idx] = vtext

        # 3) 拉取明细行
        cr_vals = self._exec(
            self._sheets.spreadsheets()
            .values()
            .get(
                spreadsheetId=self._spreadsheet_id,
                range=f"{self._tab_card_rows}!A:D",
            ),
            is_write=False,
        ).get("values", [])
        cr_rows = cr_vals[1:] if cr_vals else []

        rows_by_key: dict[str, list[tuple[int, dict[str, Any]]]] = {}
        for r in cr_rows:
            if not r or len(r) < 4:
                continue
            ck = str(r[0]).strip()
            if ck not in wanted:
                continue
            try:
                row_index = int(str(r[1]).strip() or "0")
            except Exception:
                row_index = 0
            raw_json = "" if r[3] is None else str(r[3])
            try:
                row_obj = json.loads(raw_json) if raw_json else {}
            except Exception:
                row_obj = {"_raw": raw_json}
            rows_by_key.setdefault(ck, []).append((row_index, row_obj))

        # sort rows by row_index
        sorted_rows_by_key: dict[str, list[dict[str, Any]]] = {}
        for ck, items in rows_by_key.items():
            items_sorted = sorted(items, key=lambda it: int(it[0]))
            sorted_rows_by_key[ck] = [it[1] for it in items_sorted]

        # 4) reset 看板
        self.reset_dashboard(col_l=col_l, col_r=col_r)

        # 5) 重放渲染
        y = 1
        min_slot_height = max(int(self._dashboard_slot_height), 1)
        slot_updates: dict[str, str] = {}
        for item in card_items:
            ck = item["card_key"]
            cols_map = cols_by_key.get(ck, {})
            if cols_map:
                max_i = max(cols_map.keys())
                columns = [cols_map.get(i, "") for i in range(0, max_i + 1)]
            else:
                columns = []

            payload: dict[str, Any] = {
                "card_key": ck,
                "ts_utc": item.get("ts_utc") or "",
                "source_service": item.get("source_service") or "",
                "card_type": item.get("card_type") or "",
                "header": {
                    "title": item.get("title") or "",
                    "update_time": item.get("update_time") or "",
                    "sort_desc": item.get("sort_desc") or "",
                },
                "params": {"last_update": item.get("last_update") or ""},
                "hint": {"text": hint_by_key.get(ck, "")},
                "table": {"columns": columns, "rows": sorted_rows_by_key.get(ck, [])},
                "tg": {"url": item.get("tg_url") or ""},
                "raw": {"telegram_text_full": "", "payload_json_full": {}},
            }

            if mode == "replace":
                ct = (item.get("card_type") or "").strip()
                h = self._calc_dashboard_height(payload, col_l=col_l, col_r=col_r)
                reserved = max(int(h), int(min_slot_height))
                if ct:
                    slot_updates[f"slot.{ct}.y"] = str(y)
                    slot_updates[f"slot.{ct}.h"] = str(reserved)

            self._render_dashboard(payload, y=y, col_l=col_l, col_r=col_r)
            if mode == "replace":
                y += reserved
            else:
                height = self._calc_dashboard_height(payload, col_l=col_l, col_r=col_r)
                y += height

        kv = {"dashboard_next_row": str(y), **slot_updates}
        self._meta_set(kv)
        return {"ok": True, "cards": len(card_items), "dashboard_next_row": y, "dashboard_mode": mode}

    def _load_card_priority_map(self) -> dict[str, int]:
        """
        尝试从 telegram-service 的 cards registry 加载 priority，用于“看板重建排序”。
        - 失败时返回空 dict：自动 fallback 为按 card_type 排序
        """
        try:
            import sys
            from pathlib import Path

            from src.repo import find_repo_root, find_telegram_service_src

            start = Path(__file__).resolve()
            repo_root = find_repo_root(start)
            tg_src = find_telegram_service_src(repo_root)
            if str(repo_root) not in sys.path:
                sys.path.insert(0, str(repo_root))
            if str(tg_src) not in sys.path:
                sys.path.insert(0, str(tg_src))

            from cards.registry import RankingRegistry  # type: ignore

            reg = RankingRegistry()
            reg.load_cards()
            out: dict[str, int] = {}
            for c in reg.iter_cards():
                cid = str(getattr(c, "card_id", "") or "").strip()
                if not cid:
                    continue
                try:
                    pr = int(getattr(c, "priority", 0) or 0)
                except Exception:
                    pr = 0
                out[cid] = pr
            return out
        except Exception:
            return {}

    def _migrate_legacy_tabs(self) -> None:
        """
        将历史英文 tab 名迁移为中文 tab 名。

        - 若新中文名不存在：直接 rename（保留原 sheetId 与历史数据）
        - 若新中文名已存在：把旧英文 tab 重命名为 `旧_<中文名>`，避免数据丢失
        """
        legacy_to_target = {
            "dashboard": self._tab_dashboard,
            "cards_index": self._tab_cards_index,
            "card_fields_eav": self._tab_card_fields_eav,
            "card_rows": self._tab_card_rows,
            "row_fields_eav": self._tab_row_fields_eav,
            "blobs_index": self._tab_blobs_index,
            "meta": self._tab_meta,
        }

        if not self._sheet_id_by_title:
            return

        requests: list[dict[str, Any]] = []
        for legacy, target in legacy_to_target.items():
            if legacy not in self._sheet_id_by_title:
                continue

            sheet_id = int(self._sheet_id_by_title[legacy])
            if target not in self._sheet_id_by_title:
                new_title = target
            else:
                new_title = f"旧_{target}"
                if new_title in self._sheet_id_by_title:
                    new_title = f"旧_{target}_{sheet_id}"

            requests.append(
                {
                    "updateSheetProperties": {
                        "properties": {"sheetId": sheet_id, "title": new_title},
                        "fields": "title",
                    }
                }
            )

        if not requests:
            return

        self._exec(
            self._sheets.spreadsheets().batchUpdate(
                spreadsheetId=self._spreadsheet_id,
                body={"requests": requests},
            ),
            is_write=True,
        )

    def _refresh_sheet_map(self) -> None:
        ss = self._exec(
            self._sheets.spreadsheets().get(
                spreadsheetId=self._spreadsheet_id,
                fields="sheets.properties(sheetId,title,gridProperties(rowCount,columnCount))",
            ),
            is_write=False,
        )
        out: dict[str, int] = {}
        grid: dict[str, tuple[int, int]] = {}
        for sh in ss.get("sheets", []):
            props = sh.get("properties", {})
            title = str(props.get("title"))
            out[title] = int(props.get("sheetId"))
            gp = props.get("gridProperties") or {}
            try:
                rc = int(gp.get("rowCount") or 0)
                cc = int(gp.get("columnCount") or 0)
            except Exception:
                rc, cc = 0, 0
            grid[title] = (rc, cc)
        self._sheet_id_by_title = out
        self._grid_by_title = grid

    def _ensure_grid_size(self, title: str, *, min_rows: int, min_cols: int) -> None:
        if min_rows <= 0 and min_cols <= 0:
            return

        sheet_id = self._sheet_id_by_title.get(title)
        if sheet_id is None:
            self._refresh_sheet_map()
            sheet_id = self._sheet_id_by_title.get(title)
        if sheet_id is None:
            raise RuntimeError(f"missing_sheet:{title}")

        row_count, col_count = self._grid_by_title.get(title, (0, 0))
        want_rows = max(int(min_rows), 0)
        want_cols = max(int(min_cols), 0)

        new_row_count = row_count
        new_col_count = col_count
        if want_rows > row_count:
            new_row_count = max(want_rows, row_count + 2000 if row_count > 0 else want_rows)
        if want_cols > col_count:
            new_col_count = max(want_cols, col_count + 10 if col_count > 0 else want_cols)

        if new_row_count == row_count and new_col_count == col_count:
            return

        self._exec(
            self._sheets.spreadsheets().batchUpdate(
                spreadsheetId=self._spreadsheet_id,
                body={
                    "requests": [
                        {
                            "updateSheetProperties": {
                                "properties": {
                                    "sheetId": int(sheet_id),
                                    "gridProperties": {
                                        "rowCount": int(new_row_count),
                                        "columnCount": int(new_col_count),
                                    },
                                },
                                "fields": "gridProperties.rowCount,gridProperties.columnCount",
                            }
                        }
                    ]
                },
            ),
            is_write=True,
        )
        # refresh cache
        self._refresh_sheet_map()

    def _ensure_header_row(self, sheet: str, headers: list[str]) -> None:
        rng = f"{sheet}!1:1"
        got = self._exec(
            self._sheets.spreadsheets()
            .values()
            .get(
                spreadsheetId=self._spreadsheet_id,
                range=rng,
            ),
            is_write=False,
        )
        values = got.get("values", [])
        if values and any(v != "" for v in values[0]):
            return
        self._exec(
            self._sheets.spreadsheets()
            .values()
            .update(
                spreadsheetId=self._spreadsheet_id,
                range=f"{sheet}!A1",
                valueInputOption="RAW",
                body={"values": [headers]},
            ),
            is_write=True,
        )

    # ==================== meta ====================
    def _meta_get(self) -> dict[str, str]:
        if self._schema_mode == "minimal":
            return self._local_meta_get()
        got = self._exec(
            self._sheets.spreadsheets()
            .values()
            .get(
                spreadsheetId=self._spreadsheet_id,
                range=f"{self._tab_meta}!A:B",
            ),
            is_write=False,
        )
        rows = got.get("values", [])
        out: dict[str, str] = {}
        for r in rows[1:]:  # skip header
            if not r:
                continue
            k = str(r[0]).strip() if len(r) >= 1 else ""
            v = str(r[1]) if len(r) >= 2 else ""
            if k:
                out[k] = v
        return out

    def _meta_set(self, kv: dict[str, str]) -> None:
        if self._schema_mode == "minimal":
            self._local_meta_set(kv)
            return
        # 简单 upsert：读出当前 mapping -> 更新/append（低频路径）
        got = self._exec(
            self._sheets.spreadsheets()
            .values()
            .get(
                spreadsheetId=self._spreadsheet_id,
                range=f"{self._tab_meta}!A:B",
            ),
            is_write=False,
        )
        rows = got.get("values", [])
        pos: dict[str, int] = {}
        for idx, r in enumerate(rows[1:], start=2):
            if r and len(r) >= 1 and str(r[0]).strip():
                pos[str(r[0]).strip()] = idx

        updates: list[dict[str, Any]] = []
        appends: list[list[str]] = []
        for k, v in kv.items():
            if k in pos:
                updates.append({"range": f"{self._tab_meta}!B{pos[k]}", "values": [[str(v)]]})
            else:
                appends.append([k, str(v)])

        if updates:
            self._exec(
                self._sheets.spreadsheets()
                .values()
                .batchUpdate(
                    spreadsheetId=self._spreadsheet_id,
                    body={"valueInputOption": "RAW", "data": updates},
                ),
                is_write=True,
            )

        if appends:
            self._exec(
                self._sheets.spreadsheets()
                .values()
                .append(
                    spreadsheetId=self._spreadsheet_id,
                    range=f"{self._tab_meta}!A1",
                    valueInputOption="RAW",
                    insertDataOption="INSERT_ROWS",
                    body={"values": appends},
                ),
                is_write=True,
            )

    # 运维友好：对外暴露 meta（用于节流/周期性任务）
    def meta_get(self) -> dict[str, str]:
        self.ensure_schema()
        return self._meta_get()

    def meta_set(self, kv: dict[str, str]) -> None:
        self.ensure_schema()
        self._meta_set(kv)

    def _local_meta_get(self) -> dict[str, str]:
        p = self._local_meta_path
        if not p:
            return {}
        try:
            if not p.exists():
                return {}
            data = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return {}
            out: dict[str, str] = {}
            for k, v in data.items():
                if k is None:
                    continue
                out[str(k)] = "" if v is None else str(v)
            return out
        except Exception:
            return {}

    def _local_meta_set(self, kv: dict[str, str], *, clear_prefixes: list[str] | None = None) -> None:
        p = self._local_meta_path
        if not p:
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        cur = self._local_meta_get()
        if clear_prefixes:
            for pref in clear_prefixes:
                for k in list(cur.keys()):
                    if str(k).startswith(pref):
                        cur.pop(k, None)
        for k, v in kv.items():
            cur[str(k)] = "" if v is None else str(v)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(cur, ensure_ascii=False, separators=(",", ":"), sort_keys=True), encoding="utf-8")
        tmp.replace(p)

    # ==================== write ====================
    def write_card(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.ensure_schema()

        card_key = str(payload.get("card_key") or "").strip()
        if not card_key:
            raise RuntimeError("missing_card_key")

        # 以运行时配置（进程参数/env）为真相源：避免“表内 meta 被写坏/漂移”导致列从 A 飘到 N 等错位。
        col_l = (self._dashboard_col_l or "A").strip().upper()
        col_r = (self._dashboard_col_r or "M").strip().upper()
        # 行为口径：以“运行时配置/构造参数”为准，避免表内 meta 被旧进程写坏导致模式漂移。
        mode = (self._dashboard_mode or "replace").strip().lower()
        min_slot_height = max(int(self._dashboard_slot_height), 1)
        facts_mode = (self._facts_mode or "append").strip().lower()
        if facts_mode not in {"append", "none"}:
            facts_mode = "append"
        # minimal schema：不允许写事实表（tab 会被修剪掉）；强制降级为只写看板。
        if self._schema_mode == "minimal":
            facts_mode = "none"
            self._facts_mode = "none"

        if mode not in {"append", "replace"}:
            mode = "replace"

        card_type = str(payload.get("card_type") or "").strip()
        slot_key = card_type or str(payload.get("card_key") or "").strip()
        height = self._calc_dashboard_height(payload, col_l=col_l, col_r=col_r)

        reserved_height = height
        if mode == "replace":
            slot_y_key = f"slot.{slot_key}.y"
            slot_h_key = f"slot.{slot_key}.h"
            meta = self._meta_get()
            y = int(meta.get(slot_y_key) or "0")
            prev_reserved = int(meta.get(slot_h_key) or "0")

            if y <= 0:
                y = int(meta.get("dashboard_next_row") or "1")
                reserved_height = max(height, min_slot_height)
                self._meta_set(
                    {
                        slot_y_key: str(y),
                        slot_h_key: str(reserved_height),
                        "dashboard_next_row": str(y + reserved_height),
                    }
                )
                meta = self._meta_get()
            else:
                reserved_height = max(prev_reserved, min_slot_height)
                # 如果当前卡片高度超过历史预留高度：需要“扩容”，否则会覆盖下一张卡片。
                if height > reserved_height:
                    delta = int(height - reserved_height)
                    self._dashboard_insert_rows(y=y, reserved_height=reserved_height, delta=delta, meta=meta)
                    reserved_height = height
                    # meta 已在 _dashboard_insert_rows 内更新；重新读取以免漂移
                    meta = self._meta_get()
        else:
            # append：minimal schema 不依赖 sheet meta，使用进程内 cursor；full schema 仍可用 meta
            if self._schema_mode == "minimal":
                y = int(self._append_cursor_y or 1)
            else:
                meta = self._meta_get()
                y = int(meta.get("dashboard_next_row") or "1")

        dash = {
            "sheet": self._tab_dashboard,
            "col_l": col_l,
            "col_r": col_r,
            "row_y": y,
            "height": height,
            "reserved_height": reserved_height if mode == "replace" else height,
        }

        # 1) dashboard（必须优先成功：展示面不能被事实写入失败拖垮）
        self._ensure_grid_size(
            self._tab_dashboard,
            min_rows=y + (reserved_height if mode == "replace" else height),
            min_cols=_col_to_index(col_r),
        )
        if mode == "replace":
            self._clear_dashboard_slot(y=y, slot_height=reserved_height, col_l=col_l, col_r=col_r)
        self._render_dashboard(payload, y=y, col_l=col_l, col_r=col_r)

        # 2) facts（可选：append-only；工作簿达到 1000 万 cells 上限后必须关闭）
        if facts_mode == "append":
            try:
                # blob（可选：超长 raw）——会向“大字段索引”追加一行；在 cells 上限时也会失败
                self._maybe_blob(payload)
                self._append_cards_index(payload, dash)
                self._append_card_fields_eav(payload)
                self._append_rows_eav(payload)
            except Exception as exc:
                # 触发条件：Google Sheets 1000 万 cells 上限
                msg = str(exc)
                if "above the limit of 10000000 cells" in msg:
                    # 事实表写入不可用：降级为“仅看板覆盖写”，避免服务整体卡死在 outbox
                    facts_mode = "none"
                    self._facts_mode = "none"
                else:
                    raise

        # 3) meta bump
        if mode == "append":
            if self._schema_mode == "minimal":
                self._append_cursor_y = int(y + height)
                self._local_meta_set({"dashboard_next_row": str(self._append_cursor_y)})
            else:
                self._meta_set({"dashboard_next_row": str(y + height)})
        elif mode == "replace":
            # 记录最终预留高度（非递减），用于后续清理/扩容判断
            slot_h_key = f"slot.{slot_key}.h"
            try:
                cur = int((meta.get(slot_h_key) or "0").strip() or "0")
            except Exception:
                cur = 0
            if reserved_height > cur:
                self._meta_set({slot_h_key: str(reserved_height)})

        return {"ok": True, "card_key": card_key, "idempotent": False, "dashboard": dash, "facts_mode": facts_mode}

    def prune_tabs(
        self,
        *,
        symbol_tab_prefix: str,
        keep_symbol_tabs: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        删除非必要 tab：只保留：
        - 看板（SHEETS_TAB_DASHBOARD）
        - 交易对子表（默认：title 以 symbol_tab_prefix 开头；可选：仅保留 keep_symbol_tabs）
        """
        self.ensure_schema()
        self._refresh_sheet_map()
        keep: set[str] = {self._tab_dashboard}

        # 可选：保留“看板变体 tab”（用于对比不同高密度布局）
        # 默认不保留：避免用户只想保留最小集合时被额外 tab 污染。
        keep_variants = (os.environ.get("SHEETS_PRUNE_KEEP_DASHBOARD_VARIANTS", "0") or "0").strip() == "1"
        if keep_variants:
            for t in list(self._sheet_id_by_title.keys()):
                if str(t).startswith("看板_方案"):
                    keep.add(str(t))

        if keep_symbol_tabs is not None:
            for t in keep_symbol_tabs:
                if t:
                    keep.add(str(t).strip())
        else:
            pref = (symbol_tab_prefix or "").strip()
            for t in list(self._sheet_id_by_title.keys()):
                if pref and str(t).startswith(pref):
                    keep.add(str(t))

        delete_ids: list[int] = []
        for title, sid in self._sheet_id_by_title.items():
            if title not in keep:
                delete_ids.append(int(sid))

        if not delete_ids:
            return {"deleted": 0, "kept": sorted(keep)}

        reqs = [{"deleteSheet": {"sheetId": int(sid)}} for sid in delete_ids]
        self._exec(
            self._sheets.spreadsheets().batchUpdate(
                spreadsheetId=self._spreadsheet_id,
                body={"requests": reqs},
            ),
            is_write=True,
        )
        self._refresh_sheet_map()
        return {"deleted": len(delete_ids), "kept": sorted(keep)}

    def _dashboard_insert_rows(self, *, y: int, reserved_height: int, delta: int, meta: dict[str, str]) -> None:
        """
        replace 模式扩容：
        - 在看板 sheet 中插入 delta 行，使得当前 card_type 的槽位可以增长而不覆盖下方卡片
        - 将所有 slot.*.y（在当前卡片下方的）与 dashboard_next_row 同步下移 delta
        """
        if delta <= 0:
            return

        insert_at = int(y) + int(reserved_height)  # 在槽位末尾下一行前插入

        sh_id = self._sheet_id_by_title.get(self._tab_dashboard)
        if sh_id is None:
            self._refresh_sheet_map()
            sh_id = self._sheet_id_by_title[self._tab_dashboard]

        self._exec(
            self._sheets.spreadsheets().batchUpdate(
                spreadsheetId=self._spreadsheet_id,
                body={
                    "requests": [
                        {
                            "insertDimension": {
                                "range": {
                                    "sheetId": int(sh_id),
                                    "dimension": "ROWS",
                                    "startIndex": int(insert_at) - 1,
                                    "endIndex": int(insert_at) - 1 + int(delta),
                                },
                                "inheritFromBefore": False,
                            }
                        }
                    ]
                },
            ),
            is_write=True,
        )
        # refresh grid cache（rowCount 变化）
        self._refresh_sheet_map()

        # 更新 meta：所有 y > 当前 y 的 slot 下移
        kv: dict[str, str] = {}
        for k, v in meta.items():
            if not (k.startswith("slot.") and k.endswith(".y")):
                continue
            try:
                vy = int(str(v).strip() or "0")
            except Exception:
                continue
            if vy > int(y):
                kv[k] = str(vy + int(delta))

        try:
            dn = int(str(meta.get("dashboard_next_row") or "1").strip() or "1")
        except Exception:
            dn = 1
        kv["dashboard_next_row"] = str(dn + int(delta))
        self._meta_set(kv)

    def _clear_dashboard_slot(self, *, y: int, slot_height: int, col_l: str, col_r: str) -> None:
        """
        看板覆盖写入前的“硬清理”：
        - 清空值（避免上一轮残留）
        - 解除合并（避免 merge 叠加导致 API 报错或版式错乱）
        """
        y0 = int(y)
        h = max(int(slot_height), 1)
        y1 = y0 + h - 1

        self._exec(
            self._sheets.spreadsheets()
            .values()
            .clear(
                spreadsheetId=self._spreadsheet_id,
                range=f"{self._tab_dashboard}!{col_l}{y0}:{col_r}{y1}",
            ),
            is_write=True,
        )

        sh_id = self._sheet_id_by_title.get(self._tab_dashboard)
        if sh_id is None:
            self._refresh_sheet_map()
            sh_id = self._sheet_id_by_title[self._tab_dashboard]

        col_r_idx = _col_to_index(col_r)
        # unmergeCells 必须覆盖“完整 merged range”，否则会 400：
        # - 历史上 dashboard 可能用更宽的 col_r（例如 CU），导致 merge 范围超出当前 col_r
        # - 因此这里对行范围按 slot 精确裁剪，但列范围覆盖整个 sheet 的已分配列数
        _rc, sheet_cols = self._grid_by_title.get(self._tab_dashboard, (0, 0))
        end_col = int(max(sheet_cols or 0, col_r_idx))
        self._exec(
            self._sheets.spreadsheets().batchUpdate(
                spreadsheetId=self._spreadsheet_id,
                body={
                    "requests": [
                        {
                            "unmergeCells": {
                                "range": {
                                    "sheetId": int(sh_id),
                                    "startRowIndex": y0 - 1,
                                    "endRowIndex": y1,
                                    "startColumnIndex": 0,
                                    "endColumnIndex": end_col,
                                }
                            }
                        }
                    ]
                },
            ),
            is_write=True,
        )

    def _calc_dashboard_height(self, payload: dict[str, Any], *, col_l: str, col_r: str) -> int:
        """
        计算卡片块高度（用于 y 指针推进）。
        - 支持“超宽字段分块”：columns 超出固定宽度时，按列块拆成多段子表
        - height 口径：包含底部 1 行空行分隔
        """
        col_l_idx = _col_to_index(col_l)
        col_r_idx = _col_to_index(col_r)
        width = col_r_idx - col_l_idx + 1
        if width <= 0:
            raise RuntimeError("invalid_dashboard_col_range")

        table = payload.get("table") or {}
        columns = table.get("columns") or []
        rows = table.get("rows") or []
        rows_cnt = len(rows)
        cols_cnt = len(columns)

        # chunks = max(1, ceil(cols_cnt/width))
        chunks = max(1, (cols_cnt + width - 1) // width)
        # 固定源信息1行 + 每块(字段组表头1行+周期表头1行+明细N行)*chunks + blank=1行
        return chunks * (rows_cnt + 2) + 2

    # ==================== facts writers ====================
    def _append_cards_index(self, payload: dict[str, Any], dash: dict[str, Any]) -> None:
        header = payload.get("header") or {}
        params = payload.get("params") or {}
        tg = payload.get("tg") or {}

        row = [
            str(payload.get("card_key") or ""),
            str(payload.get("ts_utc") or ""),
            str(payload.get("source_service") or ""),
            str(payload.get("card_type") or ""),
            str(header.get("title") or ""),
            str(header.get("update_time") or ""),
            str(header.get("sort_desc") or ""),
            str(params.get("last_update") or ""),
            str(tg.get("url") or ""),
            str(dash.get("sheet") or ""),
            str(dash.get("col_l") or ""),
            str(dash.get("col_r") or ""),
            str(dash.get("row_y") or ""),
            str(dash.get("height") or ""),
        ]

        self._exec(
            self._sheets.spreadsheets()
            .values()
            .append(
                spreadsheetId=self._spreadsheet_id,
                range=f"{self._tab_cards_index}!A1",
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": [row]},
            ),
            is_write=True,
        )

    def _append_card_fields_eav(self, payload: dict[str, Any]) -> None:
        card_key = str(payload.get("card_key") or "")
        rows: list[list[str]] = []
        for path, vtype, vtext in _flatten_eav("", payload):
            rows.append([card_key, path, vtext, vtype])
        self._append_rows(f"{self._tab_card_fields_eav}!A1", rows)

    def _append_rows_eav(self, payload: dict[str, Any]) -> None:
        card_key = str(payload.get("card_key") or "")
        table = payload.get("table") or {}
        rows = table.get("rows") or []
        if not rows:
            return

        card_rows: list[list[str]] = []
        eav_rows: list[list[str]] = []
        for idx, row_obj in enumerate(rows, start=1):
            row_obj = row_obj or {}
            row_key = ""
            for k in ("币种", "symbol", "Symbol"):
                if k in row_obj and row_obj.get(k) is not None:
                    row_key = str(row_obj.get(k))
                    break
            card_rows.append(
                [
                    card_key,
                    str(idx),
                    row_key,
                    json.dumps(row_obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
                ]
            )

            for path, vtype, vtext in _flatten_eav("", row_obj):
                eav_rows.append([card_key, str(idx), path, vtext, vtype])

        self._append_rows(f"{self._tab_card_rows}!A1", card_rows)
        self._append_rows(f"{self._tab_row_fields_eav}!A1", eav_rows)

    def _append_rows(self, range_a1: str, rows: list[list[str]], *, chunk: int = 500) -> None:
        if not rows:
            return
        for i in range(0, len(rows), chunk):
            part = rows[i : i + chunk]
            self._exec(
                self._sheets.spreadsheets()
                .values()
                .append(
                    spreadsheetId=self._spreadsheet_id,
                    range=range_a1,
                    valueInputOption="RAW",
                    insertDataOption="INSERT_ROWS",
                    body={"values": part},
                ),
                is_write=True,
            )

    # ==================== blobs ====================
    def _maybe_blob(self, payload: dict[str, Any]) -> None:
        raw = payload.get("raw") or {}
        if not isinstance(raw, dict):
            return

        if self._blob_threshold_chars <= 0:
            return

        created_at = _now_utc_iso()
        card_key = str(payload.get("card_key") or "")

        def put_text(blob_key: str, text: str, mime: str) -> dict[str, Any]:
            url = self._drive_put_text(
                filename=f"tg_{blob_key.replace(':', '_')}",
                text=text,
                mime=mime,
            )
            sha = _sha256_hex(text)
            self._exec(
                self._sheets.spreadsheets()
                .values()
                .append(
                    spreadsheetId=self._spreadsheet_id,
                    range=f"{self._tab_blobs_index}!A1",
                    valueInputOption="RAW",
                    insertDataOption="INSERT_ROWS",
                    body={"values": [[card_key, blob_key, sha, mime, url, str(len(text)), created_at]]},
                ),
                is_write=True,
            )
            return {"blob_url": url, "sha256": sha, "size_chars": len(text)}

        # telegram_text_full
        v = raw.get("telegram_text_full")
        if v is not None and isinstance(v, str) and len(v) > self._blob_threshold_chars:
            raw["telegram_text_full"] = put_text("raw.telegram_text_full", v, "text/plain")

        # payload_json_full
        j = raw.get("payload_json_full")
        if j is not None:
            s = j if isinstance(j, str) else json.dumps(j, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            if len(s) > self._blob_threshold_chars:
                raw["payload_json_full"] = put_text("raw.payload_json_full", s, "application/json")

        payload["raw"] = raw

    def _drive_put_text(self, *, filename: str, text: str, mime: str) -> str:
        from googleapiclient.http import MediaInMemoryUpload  # type: ignore

        media = MediaInMemoryUpload(text.encode("utf-8"), mimetype=mime, resumable=False)
        meta: dict[str, Any] = {"name": filename}
        if self._drive_folder_id:
            meta["parents"] = [self._drive_folder_id]

        file = self._exec(
            self._drive.files().create(body=meta, media_body=media, fields="id,webViewLink"), is_write=True
        )
        file_id = file["id"]

        # “公共看板”默认策略：知道链接即可读
        self._exec(
            self._drive.permissions().create(
                fileId=file_id,
                body={"type": "anyone", "role": "reader"},
                fields="id",
            ),
            is_write=True,
        )

        return str(file.get("webViewLink") or f"https://drive.google.com/file/d/{file_id}/view")

    # ==================== dashboard render ====================
    def _render_dashboard(self, payload: dict[str, Any], *, y: int, col_l: str, col_r: str) -> None:
        col_l_idx = _col_to_index(col_l)
        col_r_idx = _col_to_index(col_r)
        width = col_r_idx - col_l_idx + 1
        if width <= 0:
            raise RuntimeError("invalid_dashboard_col_range")

        header = payload.get("header") or {}
        hint = payload.get("hint") or {}
        params = payload.get("params") or {}
        table = payload.get("table") or {}
        columns = table.get("columns") or []
        rows = table.get("rows") or []

        title = str(header.get("title") or "")
        update_time = str(header.get("update_time") or "-").strip() or "-"
        sort_desc = str(header.get("sort_desc") or "-").strip() or "-"
        hint_text = str(hint.get("text") or "-").strip() or "-"
        last_update = str(params.get("last_update") or "-").strip() or "-"

        # 源信息压缩（用户要求）：固定顺序拼接进同一单元格
        info_line = " ".join(
            [
                f"📊 {title or '-'}",
                f"⏰ 更新 {update_time}",
                f"📊 排序 {sort_desc}",
                f"💡 {hint_text}",
                f"⏰ 最后更新 {last_update}",
            ]
        )

        def pad_row(first: str) -> list[str]:
            return [first] + [""] * (width - 1)

        value_rows: list[tuple[str, list[list[str]]]] = []
        value_rows.append((f"{self._tab_dashboard}!{col_l}{y}:{col_r}{y}", [pad_row(info_line)]))

        # 超宽字段：按固定宽度分块渲染（不截断列）
        chunks = [columns[i : i + width] for i in range(0, len(columns), width)] if columns else [[]]

        table_y = y + 1
        for chunk_cols in chunks:
            # header（两行）：字段组行 + 周期行
            group_row = [_parse_field_group(str(c)) for c in chunk_cols]
            period_row = [_parse_period_suffix(str(c)) for c in chunk_cols]
            group_row = group_row + [""] * (width - len(group_row))
            period_row = period_row + [""] * (width - len(period_row))
            value_rows.append((f"{self._tab_dashboard}!{col_l}{table_y}:{col_r}{table_y}", [group_row]))
            value_rows.append((f"{self._tab_dashboard}!{col_l}{table_y + 1}:{col_r}{table_y + 1}", [period_row]))

            # body（从 table_y+2 开始）
            if rows:
                body_vals: list[list[str]] = []
                for r in rows:
                    line: list[str] = []
                    for c in chunk_cols:
                        line.append("" if r.get(c) is None else str(r.get(c)))
                    line = line + [""] * (width - len(line))
                    body_vals.append(line)
                y0 = table_y + 2
                y1 = table_y + 1 + len(body_vals)
                value_rows.append((f"{self._tab_dashboard}!{col_l}{y0}:{col_r}{y1}", body_vals))

            table_y += 2 + len(rows)

        # 兼容：不再渲染独立 hint/last 行（已压缩进 info_line）
        # 保持 table_y 推进逻辑不变；底部空行由 height 预留但不写值。

        # values batchUpdate
        data = [{"range": rng, "values": vals} for rng, vals in value_rows]
        self._exec(
            self._sheets.spreadsheets()
            .values()
            .batchUpdate(
                spreadsheetId=self._spreadsheet_id,
                body={"valueInputOption": "RAW", "data": data},
            ),
            is_write=True,
        )

        # merges + formats
        sh_id = self._sheet_id_by_title.get(self._tab_dashboard)
        if sh_id is None:
            self._refresh_sheet_map()
            sh_id = self._sheet_id_by_title[self._tab_dashboard]

        # ---------- formats ----------
        # 颜色策略：
        # - 表头行：浅灰底 + 加粗（按周期列块做灰白分带，便于阅读）
        # - 表体：按周期列块灰白交替
        # - 源信息行：整行浅底
        bg_title = _rgb(0.93, 0.93, 0.93)
        bg_body_even = _rgb(0.96, 0.96, 0.96)  # 灰
        bg_body_odd = _rgb(1.0, 1.0, 1.0)  # 白
        # 表头统一底色（不随周期变化）；周期分带只作用于表体，避免“表头花里胡哨”影响读字段名
        bg_hdr_group = _rgb(0.88, 0.88, 0.88)  # 字段组行（略深）
        bg_hdr_period = _rgb(0.92, 0.92, 0.92)  # 周期行（略浅）

        def rrange(*, r0: int, r1: int, c0: int, c1: int) -> dict[str, Any]:
            return {
                "sheetId": int(sh_id),
                "startRowIndex": int(r0),
                "endRowIndex": int(r1),
                "startColumnIndex": int(c0),
                "endColumnIndex": int(c1),
            }

        col_l0 = col_l_idx - 1
        col_r1 = col_r_idx

        def repeat_bg(*, row: int, bg: dict[str, float]) -> dict[str, Any]:
            return {
                "repeatCell": {
                    "range": rrange(r0=row - 1, r1=row, c0=col_l0, c1=col_r1),
                    "cell": {"userEnteredFormat": {"backgroundColor": bg}},
                    "fields": "userEnteredFormat.backgroundColor",
                }
            }

        requests: list[dict[str, Any]] = []

        # 源信息行背景 + 加粗
        requests.append(repeat_bg(row=y, bg=bg_title))
        requests.append(
            {
                "repeatCell": {
                    "range": rrange(r0=y - 1, r1=y, c0=col_l0, c1=col_r1),
                    "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                    "fields": "userEnteredFormat.textFormat.bold",
                }
            }
        )

        # 表头/表体：按 chunk 逐段上色（chunk 是纵向堆叠，不影响列下标）
        table_y = y + 1
        for chunk_cols in chunks:
            # header rows style（bold+居中）
            requests.append(
                {
                    "repeatCell": {
                        "range": rrange(r0=table_y - 1, r1=table_y + 1, c0=col_l0, c1=col_r1),
                        "cell": {
                            "userEnteredFormat": {
                                "textFormat": {"bold": True},
                                "horizontalAlignment": "CENTER",
                                "verticalAlignment": "MIDDLE",
                                "wrapStrategy": "WRAP",
                            }
                        },
                        "fields": "userEnteredFormat(textFormat.bold,horizontalAlignment,verticalAlignment,wrapStrategy)",
                    }
                }
            )

            # 计算每列所属周期（出现顺序 -> 交替灰白）
            period_order: list[str] = []
            period_index: dict[str, int] = {}
            period_by_col: list[str] = []
            for c in chunk_cols + [""] * (width - len(chunk_cols)):
                suf = _parse_period_suffix(str(c))
                if suf and suf not in period_index:
                    period_index[suf] = len(period_order)
                    period_order.append(suf)
                period_by_col.append(suf)

            def col_bg(suf: str, *, _period_index: dict[str, int] = period_index) -> dict[str, float]:
                if not suf:
                    return bg_body_odd
                idx = int(_period_index.get(suf, 0))
                if idx % 2 == 0:
                    return bg_body_even
                return bg_body_odd

            body_bgs = [col_bg(suf) for suf in period_by_col]

            def add_bg_segments(*, row0: int, row1: int, bgs: list[dict[str, float]]) -> None:
                start = 0
                while start < width:
                    bg = bgs[start]
                    end = start + 1
                    while end < width and bgs[end] == bg:
                        end += 1
                    requests.append(
                        {
                            "repeatCell": {
                                "range": rrange(r0=row0, r1=row1, c0=col_l0 + start, c1=col_l0 + end),
                                "cell": {"userEnteredFormat": {"backgroundColor": bg}},
                                "fields": "userEnteredFormat.backgroundColor",
                            }
                        }
                    )
                    start = end

            def add_field_group_separators(*, row0: int, row1: int, _cols: list[str] = chunk_cols) -> None:
                # 在“字段组”之间加竖线分隔：对每个新字段组的第一列，加 left border。
                sep_color = _rgb(0.70, 0.70, 0.70)
                border = {"style": "SOLID_MEDIUM", "width": 2, "color": sep_color}
                last_group = ""
                for idx, c in enumerate(list(_cols) + [""] * (width - len(_cols))):
                    g = _parse_field_group(str(c))
                    if not g:
                        continue
                    if last_group and g != last_group:
                        requests.append(
                            {
                                "updateBorders": {
                                    "range": rrange(r0=row0, r1=row1, c0=col_l0 + idx, c1=col_l0 + idx + 1),
                                    "left": border,
                                }
                            }
                        )
                    last_group = g

            # header 背景（两行）
            requests.append(
                {
                    "repeatCell": {
                        "range": rrange(r0=table_y - 1, r1=table_y, c0=col_l0, c1=col_r1),
                        "cell": {"userEnteredFormat": {"backgroundColor": bg_hdr_group}},
                        "fields": "userEnteredFormat.backgroundColor",
                    }
                }
            )
            requests.append(
                {
                    "repeatCell": {
                        "range": rrange(r0=table_y, r1=table_y + 1, c0=col_l0, c1=col_r1),
                        "cell": {"userEnteredFormat": {"backgroundColor": bg_hdr_period}},
                        "fields": "userEnteredFormat.backgroundColor",
                    }
                }
            )
            # body 背景（分段）
            if rows:
                body_r0 = table_y + 1  # = (table_y+2)-1
                body_r1 = table_y + 1 + len(rows)
                add_bg_segments(row0=body_r0, row1=body_r1, bgs=body_bgs)
                # 字段组竖线分隔（覆盖 header+body）
                add_field_group_separators(row0=table_y - 1, row1=body_r1)

            # 字段组表头行：按字段名做 merge（提升可读性）
            group_names = [_parse_field_group(str(c)) for c in chunk_cols] + [""] * (width - len(chunk_cols))
            start = 0
            while start < width:
                g = group_names[start]
                end = start + 1
                while end < width and group_names[end] == g:
                    end += 1
                if g and end - start >= 2:
                    requests.append(
                        {
                            "mergeCells": {
                                "range": rrange(
                                    r0=table_y - 1,
                                    r1=table_y,
                                    c0=col_l0 + start,
                                    c1=col_l0 + end,
                                ),
                                "mergeType": "MERGE_ALL",
                            }
                        }
                    )
                start = end

            table_y += 2 + len(rows)

        # 源信息行合并（整行）
        requests.append(
            {
                "mergeCells": {
                    "range": {
                        "sheetId": sh_id,
                        "startRowIndex": y - 1,
                        "endRowIndex": y,
                        "startColumnIndex": col_l_idx - 1,
                        "endColumnIndex": col_r_idx,
                    },
                    "mergeType": "MERGE_ALL",
                }
            }
        )
        self._exec(
            self._sheets.spreadsheets().batchUpdate(
                spreadsheetId=self._spreadsheet_id,
                body={"requests": requests},
            ),
            is_write=True,
        )
