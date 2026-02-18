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
from typing import Any


def _col_to_index(col: str) -> int:
    s = (col or "").strip().upper()
    if not s or not s.isalpha():
        raise ValueError(f"invalid_column:{col}")
    idx = 0
    for ch in s:
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx


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

        # Google Sheets 默认配额很低（常见为 60 write req/min/user），不做节流会稳定触发 429。
        write_rpm = int((os.environ.get("SHEETS_SA_WRITE_RPM", "55") or "55").strip())
        self._write_limiter = _WriteRateLimiter(write_rpm)

    def _exec(self, req: Any, *, is_write: bool) -> Any:
        if is_write:
            self._write_limiter.acquire()
        return req.execute()

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

    # ==================== ops ====================
    def reset_dashboard(self, *, col_l: str, col_r: str) -> dict[str, Any]:
        """
        清理看板展示面（不动事实表）：
        - 清空看板全部单元格
        - 解除全部合并单元格
        - 重置 meta.dashboard_next_row=1，并写入新的 dashboard_col_l/dashboard_col_r
        - 清空 slot.*.y（避免“重置后仍沿用旧卡片 y”造成看起来像堆叠/错位）
        """
        self.ensure_schema()

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

        # 3) reset meta（并清空 slot y/h）
        meta = self._meta_get()
        slot_clear: dict[str, str] = {}
        for k in meta.keys():
            if k.startswith("slot.") and (k.endswith(".y") or k.endswith(".h")):
                slot_clear[k] = "0"

        kv = {
            "dashboard_next_row": "1",
            "dashboard_col_l": str(col_l).strip().upper(),
            "dashboard_col_r": str(col_r).strip().upper(),
            "dashboard_mode": self._dashboard_mode,
            "dashboard_slot_height": str(self._dashboard_slot_height),
            **slot_clear,
        }
        self._meta_set(kv)
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

    # ==================== write ====================
    def write_card(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.ensure_schema()

        card_key = str(payload.get("card_key") or "").strip()
        if not card_key:
            raise RuntimeError("missing_card_key")

        meta = self._meta_get()
        col_l = (meta.get("dashboard_col_l") or self._dashboard_col_l).strip().upper()
        col_r = (meta.get("dashboard_col_r") or self._dashboard_col_r).strip().upper()
        # 行为口径：以“运行时配置/构造参数”为准，避免表内 meta 被旧进程写坏导致模式漂移。
        mode = (self._dashboard_mode or "replace").strip().lower()
        min_slot_height = max(int(self._dashboard_slot_height), 1)
        facts_mode = (self._facts_mode or "append").strip().lower()
        if facts_mode not in {"append", "none"}:
            facts_mode = "append"

        if mode not in {"append", "replace"}:
            mode = "replace"

        card_type = str(payload.get("card_type") or "").strip()
        slot_key = card_type or str(payload.get("card_key") or "").strip()
        height = self._calc_dashboard_height(payload, col_l=col_l, col_r=col_r)

        reserved_height = height
        if mode == "replace":
            slot_y_key = f"slot.{slot_key}.y"
            slot_h_key = f"slot.{slot_key}.h"
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

        col_l_idx = _col_to_index(col_l)
        col_r_idx = _col_to_index(col_r)
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
                                    "startColumnIndex": col_l_idx - 1,
                                    "endColumnIndex": col_r_idx,
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
        # 固定头部3行 + 每块(表头1行+明细N行)*chunks + hint/last/blank=3行
        return chunks * (rows_cnt + 1) + 6

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
        update = f"⏰ 更新 {header.get('update_time')}" if header.get("update_time") else ""
        sort = f"📊 排序 {header.get('sort_desc')}" if header.get("sort_desc") else ""
        hint_line = f"💡 {hint.get('text')}" if hint.get("text") else ""
        last_line = f"⏰ 最后更新 {params.get('last_update')}" if params.get("last_update") else ""

        def pad_row(first: str) -> list[str]:
            return [first] + [""] * (width - 1)

        value_rows: list[tuple[str, list[list[str]]]] = []
        value_rows.append((f"{self._tab_dashboard}!{col_l}{y}:{col_r}{y}", [pad_row(title)]))
        value_rows.append((f"{self._tab_dashboard}!{col_l}{y + 1}:{col_r}{y + 1}", [pad_row(update)]))
        value_rows.append((f"{self._tab_dashboard}!{col_l}{y + 2}:{col_r}{y + 2}", [pad_row(sort)]))

        # 超宽字段：按固定宽度分块渲染（不截断列）
        chunks = [columns[i : i + width] for i in range(0, len(columns), width)] if columns else [[]]

        table_y = y + 3
        for chunk_cols in chunks:
            # header
            hdr = [str(c) for c in chunk_cols]
            hdr = hdr + [""] * (width - len(hdr))
            value_rows.append((f"{self._tab_dashboard}!{col_l}{table_y}:{col_r}{table_y}", [hdr]))

            # body
            if rows:
                body_vals: list[list[str]] = []
                for r in rows:
                    line: list[str] = []
                    for c in chunk_cols:
                        line.append("" if r.get(c) is None else str(r.get(c)))
                    line = line + [""] * (width - len(line))
                    body_vals.append(line)
                y0 = table_y + 1
                y1 = table_y + len(body_vals)
                value_rows.append((f"{self._tab_dashboard}!{col_l}{y0}:{col_r}{y1}", body_vals))

            table_y += 1 + len(rows)

        hint_y = table_y
        last_y = table_y + 1
        value_rows.append((f"{self._tab_dashboard}!{col_l}{hint_y}:{col_r}{hint_y}", [pad_row(hint_line)]))
        value_rows.append((f"{self._tab_dashboard}!{col_l}{last_y}:{col_r}{last_y}", [pad_row(last_line)]))

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
        # - title/update/sort/hint/last：整行浅底
        bg_title = _rgb(0.93, 0.93, 0.93)
        bg_meta = _rgb(0.97, 0.97, 0.97)
        bg_body_even = _rgb(0.96, 0.96, 0.96)  # 灰
        bg_body_odd = _rgb(1.0, 1.0, 1.0)  # 白
        bg_hdr_even = _rgb(0.90, 0.90, 0.90)
        bg_hdr_odd = _rgb(0.97, 0.97, 0.97)

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

        # title/update/sort/hint/last 背景
        requests.append(repeat_bg(row=y, bg=bg_title))
        requests.append(repeat_bg(row=y + 1, bg=bg_meta))
        requests.append(repeat_bg(row=y + 2, bg=bg_meta))
        requests.append(repeat_bg(row=hint_y, bg=bg_meta))
        requests.append(repeat_bg(row=last_y, bg=bg_meta))

        # title 行加粗
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
        table_y = y + 3
        for chunk_cols in chunks:
            # header row style（bold+居中）
            requests.append(
                {
                    "repeatCell": {
                        "range": rrange(r0=table_y - 1, r1=table_y, c0=col_l0, c1=col_r1),
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

            def col_bg(is_header: bool, suf: str, *, _period_index: dict[str, int] = period_index) -> dict[str, float]:
                if not suf:
                    return bg_hdr_odd if is_header else bg_body_odd
                idx = int(_period_index.get(suf, 0))
                if idx % 2 == 0:
                    return bg_hdr_even if is_header else bg_body_even
                return bg_hdr_odd if is_header else bg_body_odd

            hdr_bgs = [col_bg(True, suf) for suf in period_by_col]
            body_bgs = [col_bg(False, suf) for suf in period_by_col]

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

            # header 背景（分段）
            add_bg_segments(row0=table_y - 1, row1=table_y, bgs=hdr_bgs)
            # body 背景（分段）
            if rows:
                body_r0 = table_y  # = (table_y+1)-1
                body_r1 = table_y + len(rows)
                add_bg_segments(row0=body_r0, row1=body_r1, bgs=body_bgs)

            table_y += 1 + len(rows)

        merge_rows = [y, y + 1, y + 2, hint_y, last_y]
        for ry in merge_rows:
            requests.append(
                {
                    "mergeCells": {
                        "range": {
                            "sheetId": sh_id,
                            "startRowIndex": ry - 1,
                            "endRowIndex": ry,
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
