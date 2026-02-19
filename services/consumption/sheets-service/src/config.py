from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    write_mode: str  # webhook|sa
    sync_mode: str  # dashboard|snapshot|append
    force_render: bool
    dashboard_auto_width: bool
    schema_mode: str  # full|minimal
    local_meta_path: Path

    # ---------- webhook writer ----------
    webhook_url: str
    webhook_secret: str
    webhook_timeout_seconds: int
    webhook_max_retries: int
    webhook_backoff_base_seconds: float
    webhook_backoff_max_seconds: float

    # ---------- service account writer ----------
    spreadsheet_id: str
    sa_credentials_path: str
    drive_folder_id: str
    share_email: str
    public_read: bool
    dashboard_col_l: str
    dashboard_col_r: str
    dashboard_mode: str  # append|replace
    dashboard_slot_height: int
    facts_mode: str  # append|none
    blob_threshold_chars: int

    # ---------- common ----------
    export_lang: str
    export_cards: str
    symbol_tabs: list[str]
    symbol_tab_prefix: str
    symbol_tabs_mode: str  # dashboard|every|none
    symbol_tabs_interval_seconds: int
    include_blacklist: bool
    interval_seconds: int
    dry_run: bool
    outbox_path: Path
    checkpoint_path: Path
    idempotency_db_path: Path

    @staticmethod
    def from_env(service_dir: Path) -> Settings:
        write_mode = os.environ.get("SHEETS_WRITE_MODE", "webhook").strip() or "webhook"
        default_sync_mode = "dashboard" if write_mode == "sa" else "snapshot"
        sync_mode = (os.environ.get("SHEETS_SYNC_MODE", default_sync_mode) or default_sync_mode).strip().lower()
        if sync_mode not in {"dashboard", "snapshot", "append"}:
            sync_mode = default_sync_mode
        force_render = os.environ.get("SHEETS_FORCE_RENDER", "0").strip() == "1"
        dashboard_auto_width = os.environ.get("SHEETS_DASHBOARD_AUTO_WIDTH", "1").strip() != "0"
        schema_mode = (os.environ.get("SHEETS_SCHEMA_MODE", "full") or "full").strip().lower()
        if schema_mode not in {"full", "minimal"}:
            schema_mode = "full"

        webhook_url = os.environ.get("SHEETS_WEBHOOK_URL", "").strip()
        webhook_secret = os.environ.get("SHEETS_WEBHOOK_SECRET", "").strip()
        webhook_timeout_seconds = int(os.environ.get("SHEETS_WEBHOOK_TIMEOUT_SECONDS", "10").strip() or "10")
        webhook_max_retries = int(os.environ.get("SHEETS_WEBHOOK_MAX_RETRIES", "3").strip() or "3")
        webhook_backoff_base_seconds = float(
            os.environ.get("SHEETS_WEBHOOK_BACKOFF_BASE_SECONDS", "1.0").strip() or "1.0"
        )
        webhook_backoff_max_seconds = float(
            os.environ.get("SHEETS_WEBHOOK_BACKOFF_MAX_SECONDS", "30.0").strip() or "30.0"
        )

        spreadsheet_id = os.environ.get("SHEETS_SPREADSHEET_ID", "").strip()
        sa_credentials_path = (
            os.environ.get("SHEETS_SA_CREDENTIALS_PATH", "").strip()
            or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
        )
        drive_folder_id = os.environ.get("SHEETS_DRIVE_FOLDER_ID", "").strip()
        share_email = os.environ.get("SHEETS_SHARE_EMAIL", "").strip()
        public_read = os.environ.get("SHEETS_PUBLIC_READ", "0").strip() == "1"
        # 默认从第一列开始渲染。
        # - 若开启多周期横向（且保留全字段）：列数会显著增加；默认把右边界放宽到 BS（71 列）
        # - 否则默认 M（13 列）
        export_multi = os.environ.get("SHEETS_EXPORT_MULTI_PERIODS", "1").strip() != "0"
        default_col_r = "BS" if export_multi else "M"
        dashboard_col_l = (os.environ.get("SHEETS_DASHBOARD_COL_L", "A").strip() or "A").upper()
        dashboard_col_r = (os.environ.get("SHEETS_DASHBOARD_COL_R", default_col_r).strip() or default_col_r).upper()
        # dashboard 渲染模式：
        # - append：每次写入追加到末尾（审计流水视角）
        # - replace：按 card_type 固定槽位覆盖写（看板视角，默认）
        dashboard_mode = (os.environ.get("SHEETS_DASHBOARD_MODE", "replace").strip() or "replace").lower()
        # replace 模式槽位“最小预留高度”（行数）。
        # 实际预留高度= max(最小预留高度, 该 card_type 当前渲染高度)，并记录在 meta.slot.<card_type>.h。
        # 这么做的目的：
        # - 避免“固定大高度”导致卡片之间出现巨大空洞
        # - 仍保留最小缓冲区，减少偶发高度波动导致的覆盖风险
        dashboard_slot_height = int(os.environ.get("SHEETS_DASHBOARD_SLOT_HEIGHT", "10").strip() or "10")
        facts_mode = (os.environ.get("SHEETS_FACTS_MODE", "append").strip() or "append").lower()
        if facts_mode not in {"append", "none"}:
            facts_mode = "append"
        blob_threshold_chars = int(os.environ.get("SHEETS_BLOB_THRESHOLD_CHARS", "20000").strip() or "20000")

        export_lang = os.environ.get("SHEETS_EXPORT_LANG", "zh_CN").strip() or "zh_CN"
        export_cards = os.environ.get("SHEETS_EXPORT_CARDS", "").strip()
        symbol_tabs_raw = (os.environ.get("SHEETS_SYMBOL_TABS", "") or "").strip()
        if not symbol_tabs_raw:
            symbol_tabs_raw = (os.environ.get("SYMBOLS_GROUP_main4", "") or "").strip()
        if not symbol_tabs_raw:
            symbol_tabs_raw = "BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT"
        symbol_tabs = [s.strip().upper() for s in symbol_tabs_raw.split(",") if s.strip()]
        symbol_tab_prefix = (os.environ.get("SHEETS_SYMBOL_TAB_PREFIX", "币种查询_") or "币种查询_").strip()
        symbol_tabs_mode = (os.environ.get("SHEETS_SYMBOL_TABS_MODE", "dashboard") or "dashboard").strip().lower()
        if symbol_tabs_mode not in {"dashboard", "every", "none"}:
            symbol_tabs_mode = "dashboard"
        symbol_tabs_interval_seconds = int(
            (os.environ.get("SHEETS_SYMBOL_TABS_INTERVAL_SECONDS", "900") or "900").strip()
        )
        include_blacklist = os.environ.get("SHEETS_EXPORT_INCLUDE_BLACKLIST", "0").strip() == "1"
        interval_seconds = int(os.environ.get("SHEETS_SYNC_INTERVAL_SECONDS", "60").strip() or "60")
        dry_run = os.environ.get("SHEETS_SYNC_DRY_RUN", "0").strip() == "1"

        outbox_env = os.environ.get("SHEETS_OUTBOX_PATH", "").strip()
        ckpt_env = os.environ.get("SHEETS_CHECKPOINT_PATH", "").strip()
        outbox_path = Path(outbox_env).expanduser() if outbox_env else (service_dir / "data" / "outbox.jsonl")
        checkpoint_path = Path(ckpt_env).expanduser() if ckpt_env else (service_dir / "data" / "checkpoint.json")

        idem_env = os.environ.get("SHEETS_IDEMPOTENCY_DB_PATH", "").strip()
        idempotency_db_path = Path(idem_env).expanduser() if idem_env else (service_dir / "data" / "idempotency.db")

        local_meta_env = os.environ.get("SHEETS_LOCAL_META_PATH", "").strip()
        local_meta_path = (
            Path(local_meta_env).expanduser() if local_meta_env else (service_dir / "data" / "local_meta.json")
        )

        return Settings(
            write_mode=write_mode,
            sync_mode=sync_mode,
            force_render=force_render,
            dashboard_auto_width=dashboard_auto_width,
            schema_mode=schema_mode,
            local_meta_path=local_meta_path,
            webhook_url=webhook_url,
            webhook_secret=webhook_secret,
            webhook_timeout_seconds=webhook_timeout_seconds,
            webhook_max_retries=webhook_max_retries,
            webhook_backoff_base_seconds=webhook_backoff_base_seconds,
            webhook_backoff_max_seconds=webhook_backoff_max_seconds,
            spreadsheet_id=spreadsheet_id,
            sa_credentials_path=sa_credentials_path,
            drive_folder_id=drive_folder_id,
            share_email=share_email,
            public_read=public_read,
            dashboard_col_l=dashboard_col_l,
            dashboard_col_r=dashboard_col_r,
            dashboard_mode=dashboard_mode,
            dashboard_slot_height=dashboard_slot_height,
            facts_mode=facts_mode,
            blob_threshold_chars=blob_threshold_chars,
            export_lang=export_lang,
            export_cards=export_cards,
            symbol_tabs=symbol_tabs,
            symbol_tab_prefix=symbol_tab_prefix,
            symbol_tabs_mode=symbol_tabs_mode,
            symbol_tabs_interval_seconds=symbol_tabs_interval_seconds,
            include_blacklist=include_blacklist,
            interval_seconds=interval_seconds,
            dry_run=dry_run,
            outbox_path=outbox_path,
            checkpoint_path=checkpoint_path,
            idempotency_db_path=idempotency_db_path,
        )
