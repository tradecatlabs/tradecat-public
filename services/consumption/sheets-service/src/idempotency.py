from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class _SheetsConfig:
    spreadsheet_id: str
    credentials_path: str
    tab_title: str


class SheetsIdempotencyStore:
    """幂等存储（写入到 Google Sheets 自身：隐藏 tab 追加写）

目标：
- consumption 层不直连数据库
- 幂等状态与目标工作簿同生命周期，便于多机/多进程共享

实现：
- 在工作簿中维护一个隐藏 tab（默认：`幂等`）
- A 列保存已发送的 card_key（append-only）
"""

    def __init__(self, *, cfg: _SheetsConfig) -> None:
        self._cfg = cfg
        self._sheet_id: int | None = None
        self._keys: set[str] = set()
        self._svc = self._build_svc(cfg.credentials_path)
        self._ensure_tab_and_load()

    @staticmethod
    def _build_svc(credentials_path: str):
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build

        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_file(credentials_path, scopes=scopes)
        return build("sheets", "v4", credentials=creds, cache_discovery=False)

    def _fetch_sheet_map(self) -> dict[str, int]:
        ss = (
            self._svc.spreadsheets()
            .get(spreadsheetId=self._cfg.spreadsheet_id, fields="sheets(properties(sheetId,title,hidden))")
            .execute()
        )
        out: dict[str, int] = {}
        for sh in (ss.get("sheets") or []):
            p = (sh.get("properties") or {}) if isinstance(sh, dict) else {}
            title = str(p.get("title") or "")
            try:
                sid = int(p.get("sheetId"))
            except Exception:
                continue
            if title:
                out[title] = sid
        return out

    def _ensure_tab_and_load(self) -> None:
        tab = self._cfg.tab_title
        mapping = self._fetch_sheet_map()
        if tab not in mapping:
            self._svc.spreadsheets().batchUpdate(
                spreadsheetId=self._cfg.spreadsheet_id,
                body={
                    "requests": [
                        {
                            "addSheet": {
                                "properties": {
                                    "title": tab,
                                    "hidden": True,
                                    "gridProperties": {"rowCount": 2, "columnCount": 1},
                                }
                            }
                        }
                    ]
                },
            ).execute()
            mapping = self._fetch_sheet_map()
        self._sheet_id = mapping.get(tab)

        # header（A1）
        got = (
            self._svc.spreadsheets()
            .values()
            .get(spreadsheetId=self._cfg.spreadsheet_id, range=f"{tab}!A1:A1")
            .execute()
        )
        values = got.get("values") or []
        if not values or not values[0] or str(values[0][0]).strip() != "card_key":
            self._svc.spreadsheets().values().update(
                spreadsheetId=self._cfg.spreadsheet_id,
                range=f"{tab}!A1",
                valueInputOption="RAW",
                body={"values": [["card_key"]]},
            ).execute()

        # load keys（A2:A）
        got = (
            self._svc.spreadsheets()
            .values()
            .get(spreadsheetId=self._cfg.spreadsheet_id, range=f"{tab}!A2:A")
            .execute()
        )
        rows = got.get("values") or []
        for r in rows:
            if not r:
                continue
            k = str(r[0]).strip()
            if k:
                self._keys.add(k)

    def has(self, card_key: str) -> bool:
        k = (card_key or "").strip()
        if not k:
            return False
        return k in self._keys

    def mark(self, card_key: str) -> None:
        k = (card_key or "").strip()
        if not k or k in self._keys:
            return
        tab = self._cfg.tab_title
        # append-only：允许幂等表增长；此表默认隐藏且只存一列
        self._svc.spreadsheets().values().append(
            spreadsheetId=self._cfg.spreadsheet_id,
            range=f"{tab}!A1",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [[k]]},
        ).execute()
        self._keys.add(k)

    @staticmethod
    def from_env() -> SheetsIdempotencyStore:
        spreadsheet_id = (os.environ.get("SHEETS_SPREADSHEET_ID") or "").strip()
        credentials_path = (
            (os.environ.get("SHEETS_SA_CREDENTIALS_PATH") or "").strip()
            or (os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or "").strip()
        )
        if not spreadsheet_id:
            raise RuntimeError("missing_env:SHEETS_SPREADSHEET_ID")
        if not credentials_path:
            raise RuntimeError("missing_env:SHEETS_SA_CREDENTIALS_PATH")
        tab = (os.environ.get("SHEETS_TAB_IDEMPOTENCY") or "幂等").strip() or "幂等"
        return SheetsIdempotencyStore(cfg=_SheetsConfig(spreadsheet_id=spreadsheet_id, credentials_path=credentials_path, tab_title=tab))


class LocalIdempotencyStore:
    """幂等存储（本地文件，按行追加）——用于 webhook 模式（无 SA 凭证）"""

    def __init__(self, *, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._keys: set[str] = set()
        if self._path.exists():
            for line in self._path.read_text(encoding="utf-8").splitlines():
                k = line.strip()
                if k:
                    self._keys.add(k)

    def has(self, card_key: str) -> bool:
        k = (card_key or "").strip()
        if not k:
            return False
        return k in self._keys

    def mark(self, card_key: str) -> None:
        k = (card_key or "").strip()
        if not k or k in self._keys:
            return
        with self._path.open("a", encoding="utf-8") as f:
            f.write(k + "\n")
        self._keys.add(k)


class IdempotencyStore:
    """幂等存储统一入口：优先写入 Sheets，自身不可用时回退到本地文件。"""

    def __init__(self) -> None:
        write_mode = (os.environ.get("SHEETS_WRITE_MODE") or "webhook").strip().lower() or "webhook"
        if write_mode == "sa":
            try:
                self._impl = SheetsIdempotencyStore.from_env()
                return
            except Exception:
                # SA 配置缺失时回退本地文件（仍然不直连数据库）
                pass

        # webhook/default：本地幂等（仅用于避免同一 outbox 重复刷屏）
        service_dir = Path(__file__).resolve().parents[1]
        default_path = service_dir / "data" / "idempotency_keys.txt"
        path = Path((os.environ.get("SHEETS_IDEMPOTENCY_LOCAL_PATH") or str(default_path)).strip()).expanduser()
        self._impl = LocalIdempotencyStore(path=path)

    def has(self, card_key: str) -> bool:
        return bool(self._impl.has(card_key))

    def mark(self, card_key: str) -> None:
        self._impl.mark(card_key)

