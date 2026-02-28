from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import replace
from pathlib import Path

from dotenv import load_dotenv

from src.config import Settings
from src.dashboard_dedup import inject_base_card_and_dedup
from src.dashboard_variants import field_rows_period_columns
from src.idempotency import IdempotencyStore
from src.mock_webhook_server import serve_mock_webhook
from src.outbox import JsonlOutbox
from src.polymarket_facts_exporter import export_polymarket_facts_events_sheet
from src.polymarket_exporter import export_polymarket_stats_sheet
from src.repo import find_repo_root
from src.sa_sheets_writer import SaSheetsWriter
from src.symbol_query_exporter import export_symbol_query_sheet, normalize_symbol_tab_title
from src.tg_cards_exporter import TgCardsExporter
from src.webhook_client import SheetsWebhookClient


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Sync local TG cards to Google Sheets")
    p.add_argument("--once", action="store_true", help="只执行一次：导出卡片 -> 写 outbox -> flush")
    p.add_argument("--daemon", action="store_true", help="守护模式：按间隔循环执行")
    p.add_argument("--mock-webhook", action="store_true", help="启动本地 mock webhook（用于离线验收）")
    p.add_argument("--dry-run", action="store_true", help="不发网络请求，只打印 payload 概要")
    p.add_argument("--force", action="store_true", help="强制重渲染：忽略幂等（用于版式/样式大改后刷新）")
    p.add_argument("--write-mode", default="", help="写入模式：webhook|sa（默认读 env: SHEETS_WRITE_MODE）")
    p.add_argument("--bootstrap", action="store_true", help="SA 模式：创建/初始化工作簿并配置权限（全 CLI）")
    p.add_argument("--bootstrap-title", default="TradeCat TG Cards Dashboard", help="SA 模式：新建工作簿标题")
    p.add_argument("--reset-dashboard", action="store_true", help="SA 模式：清空看板并重置 y 指针/列区间")
    p.add_argument("--rebuild-dashboard", action="store_true", help="SA 模式：从事实表重建看板（可能较慢）")
    p.add_argument("--delete-tab", default="", help="SA 模式：删除指定 tab（精确匹配 title）")
    p.add_argument(
        "--prune-tabs",
        action="store_true",
        help="SA 模式：删除非必要 tab（仅保留 看板 + 配置的币种查询子表）",
    )
    p.add_argument("--dashboard-variants", action="store_true", help="SA 模式：生成 3 套高密度看板变体（新建 tab）")
    p.add_argument(
        "--dashboard-variants-only",
        action="store_true",
        help="SA 模式：仅生成看板变体（不重绘主看板；用于避免写入配额压力）",
    )
    p.add_argument(
        "--snapshot-polymarket-col-widths",
        action="store_true",
        help="SA 模式：读取 Polymarket 三表当前列宽并输出 env 配置行（只读，不写入）",
    )
    p.add_argument("--rebuild-max-cards", type=int, default=200, help="重建：只取最后 N 张卡片（默认 200）")
    p.add_argument("--cards", default="", help="逗号分隔 card_id 白名单；空=全部")
    p.add_argument("--lang", default="", help="导出语言（默认 zh_CN）")
    p.add_argument("--mock-port", type=int, default=18080, help="mock webhook 监听端口（默认 18080）")
    return p.parse_args()


def _should_retry(status: int) -> bool:
    # 约定：
    # - status=0：网络层错误（URLError）
    # - 429/5xx：上游限流/临时错误
    return status == 0 or status == 429 or (500 <= status <= 599)


def _env_bool(key: str, default: str = "0") -> bool:
    raw = (os.environ.get(key, default) or default).strip().lower()
    return raw not in {"0", "off", "false", "no", ""}


def _sleep_backoff(attempt: int, *, base: float, max_seconds: float) -> None:
    # attempt: 1..N
    delay = min(base * (2 ** (attempt - 1)), max_seconds)
    time.sleep(max(delay, 0.0))


def _post_with_retry(
    client: SheetsWebhookClient,
    payload: dict,
    *,
    max_retries: int,
    backoff_base_seconds: float,
    backoff_max_seconds: float,
) -> tuple[bool, int, dict]:
    attempt = 0
    while True:
        resp = client.post_json(payload)
        if resp.ok:
            return True, resp.status, resp.body

        if not _should_retry(resp.status):
            return False, resp.status, resp.body

        attempt += 1
        if attempt > max_retries:
            return False, resp.status, resp.body

        _sleep_backoff(attempt, base=backoff_base_seconds, max_seconds=backoff_max_seconds)


def _extract_volume_sorted_symbols(payloads: list[dict]) -> list[str]:
    """
    统一交易对排序口径：使用“成交量榜单（volume_ranking）”的行顺序作为全局币种顺序。
    - volume_ranking 的 base_period 默认 15m。
    - 在 sheets-service 导出侧会默认把 volume_ranking 改为按成交额（quote_volume）降序排序，
      因此其 rows 顺序即“按交易量(成交额)排序”。
    - 不做数值解析（避免 K/M/B 格式与语言变化引入误差）。
    """
    card_type = (os.environ.get("SHEETS_SYMBOL_SORT_CARD_TYPE", "volume_ranking") or "volume_ranking").strip()
    if not card_type:
        card_type = "volume_ranking"

    vol_payload = None
    for p in payloads:
        if str(p.get("card_type") or "").strip() == card_type:
            vol_payload = p
            break
    if not isinstance(vol_payload, dict):
        return []

    table = vol_payload.get("table") or {}
    cols = table.get("columns") or []
    rows = table.get("rows") or []
    if not (isinstance(cols, list) and isinstance(rows, list) and cols):
        return []

    sym_key = str(cols[0] or "").strip() or "币种"
    out: list[str] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        sym = str(r.get(sym_key) or r.get("币种") or r.get("symbol") or "").strip()
        if sym and sym not in out:
            out.append(sym)
    return out


def _reorder_payload_rows_by_symbols(payload: dict, *, symbols: list[str]) -> None:
    table = payload.get("table") or {}
    cols = table.get("columns") or []
    rows = table.get("rows") or []
    if not (isinstance(cols, list) and isinstance(rows, list) and cols and rows):
        return

    sym_key = str(cols[0] or "").strip() or "币种"
    order = {s: i for i, s in enumerate(symbols or [])}

    indexed: list[tuple[int, int, object]] = []
    for i, r in enumerate(rows):
        if not isinstance(r, dict):
            indexed.append((10**9, i, r))
            continue
        sym = str(r.get(sym_key) or r.get("币种") or r.get("symbol") or "").strip()
        indexed.append((int(order.get(sym, 10**9)), int(i), r))

    indexed.sort(key=lambda t: (t[0], t[1]))
    table["rows"] = [t[2] for t in indexed]
    payload["table"] = table


async def _run_once(
    settings: Settings,
    *,
    only_cards: list[str] | None,
    lang: str,
    dashboard_variants: bool,
    dashboard_variants_only: bool,
) -> int:
    if settings.write_mode == "webhook":
        if not settings.webhook_url or not settings.webhook_secret:
            print("❌ 缺少 SHEETS_WEBHOOK_URL / SHEETS_WEBHOOK_SECRET，无法发送（可先用 SHEETS_SYNC_DRY_RUN=1）")
            return 2
    elif settings.write_mode == "sa":
        if not settings.sa_credentials_path:
            print("❌ 缺少 GOOGLE_APPLICATION_CREDENTIALS / SHEETS_SA_CREDENTIALS_PATH，无法使用 SA 写入")
            return 2
        if not settings.spreadsheet_id:
            print("❌ 缺少 SHEETS_SPREADSHEET_ID（可先运行 --bootstrap 创建工作簿）")
            return 2
    else:
        print(f"❌ 不支持的 SHEETS_WRITE_MODE={settings.write_mode}（仅支持 webhook|sa）")
        return 2

    # dashboard 模式：每轮把“看板”作为展示面整体覆盖重绘（避免 slot 高度非递减导致的空洞/错位）
    # - 只建议用于 SA 模式（纯 CLI，可直接 reset+写入）
    # - webhook 模式无法安全 reset，因此自动降级为 snapshot
    is_dashboard_mode = settings.sync_mode == "dashboard" and settings.write_mode == "sa"

    webhook_client = None
    sa_writer = None
    if settings.write_mode == "webhook":
        webhook_client = SheetsWebhookClient(
            settings.webhook_url,
            settings.webhook_secret,
            timeout_seconds=settings.webhook_timeout_seconds,
        )
    elif settings.write_mode == "sa":
        sa_writer = SaSheetsWriter(
            spreadsheet_id=settings.spreadsheet_id,
            credentials_path=settings.sa_credentials_path,
            dashboard_col_l=settings.dashboard_col_l,
            dashboard_col_r=settings.dashboard_col_r,
            dashboard_mode=settings.dashboard_mode,
            dashboard_slot_height=settings.dashboard_slot_height,
            facts_mode=settings.facts_mode,
            share_email=settings.share_email,
            public_read=settings.public_read,
            drive_folder_id=settings.drive_folder_id,
            blob_threshold_chars=settings.blob_threshold_chars,
            timeout_seconds=settings.webhook_timeout_seconds,
            schema_mode=settings.schema_mode,
            local_meta_path=settings.local_meta_path,
        )
    else:
        print(f"❌ 不支持的 SHEETS_WRITE_MODE={settings.write_mode}（仅支持 webhook|sa）")
        return 2

    def _send_one(payload: dict) -> tuple[bool, int, dict]:
        if settings.write_mode == "webhook":
            assert webhook_client is not None
            return _post_with_retry(
                webhook_client,
                payload,
                max_retries=settings.webhook_max_retries,
                backoff_base_seconds=settings.webhook_backoff_base_seconds,
                backoff_max_seconds=settings.webhook_backoff_max_seconds,
            )

        assert sa_writer is not None
        attempt = 0
        last_status = 0
        last_body: dict = {}
        while True:
            try:
                body = sa_writer.write_card(payload)
                return True, 200, body
            except Exception as exc:
                last_status = int(getattr(getattr(exc, "resp", None), "status", 0) or 0)
                last_body = {"error": f"{type(exc).__name__}: {exc}"}
                if not _should_retry(last_status):
                    return False, last_status, last_body
                attempt += 1
                if attempt > settings.webhook_max_retries:
                    return False, last_status, last_body
                _sleep_backoff(
                    attempt,
                    base=settings.webhook_backoff_base_seconds,
                    max_seconds=settings.webhook_backoff_max_seconds,
                )

    # dashboard 模式：不走 outbox/idempotency（每轮全量重绘；失败下轮重试即可）
    if is_dashboard_mode:
        exporter = TgCardsExporter(include_blacklist=settings.include_blacklist, lang=lang)
        results = await exporter.export(only_cards=only_cards)

        payloads: list[dict] = []
        for r in results:
            if r.event is None:
                continue
            payload = r.event.to_dict()
            payloads.append(payload)

        # 主看板去重：把“重复基础字段”抽到第一个“基础数据”卡片，其它卡片删掉这些列
        payloads = inject_base_card_and_dedup(payloads)

        # 选择主看板渲染方案：
        # - v5：字段纵向 + 周期横向（宽度稳定、可冻结、可筛选；当前默认）
        # - legacy：保留原始“超宽分块纵向堆叠”渲染
        main_variant = (os.environ.get("SHEETS_DASHBOARD_MAIN_VARIANT", "5") or "5").strip().lower()
        use_v5_main = main_variant in {"5", "v5", "方案5"}

        # 统一交易对排序：按“成交量榜单”行顺序作为全局币种顺序（即按交易量排序）
        # - 默认开启，可用 SHEETS_SYMBOL_SORT_BY_VOLUME=0 关闭
        if use_v5_main and (os.environ.get("SHEETS_SYMBOL_SORT_BY_VOLUME", "1") or "1").strip() != "0":
            syms = _extract_volume_sorted_symbols(payloads)
            if syms:
                for p in payloads:
                    _reorder_payload_rows_by_symbols(p, symbols=syms)

        # 为 auto width 预估列数（v5 固定 10 列：卡片/币种/字段/7周期；legacy 取原始最大列数）
        if use_v5_main:
            max_cols = 10
        else:
            max_cols = 1
            for payload in payloads:
                cols = (payload.get("table") or {}).get("columns") or []
                try:
                    max_cols = max(max_cols, len(cols))
                except Exception:
                    pass

        if settings.dry_run:
            print(
                f"[dry-run] mode=dashboard cards={len(payloads)} max_cols={max_cols} spreadsheet_id={settings.spreadsheet_id}"
            )
            return 0

        assert sa_writer is not None
        # minimal schema：确保只保留“主看板 + 配置的币种查询 tab”，避免旧表残留/复活。
        if settings.schema_mode == "minimal":
            keep_symbol_tabs = []
            for sym in settings.symbol_tabs or []:
                keep_symbol_tabs.append(normalize_symbol_tab_title(symbol=sym, prefix=settings.symbol_tab_prefix))
            try:
                sa_writer.prune_tabs(symbol_tab_prefix=settings.symbol_tab_prefix, keep_symbol_tabs=keep_symbol_tabs)
            except Exception as exc:
                print(f"⚠️ prune_tabs 失败（将继续执行）：{type(exc).__name__}: {exc}")

        # 自动宽度：避免“超宽表头纵向分块”让用户误以为列丢失
        col_l = settings.dashboard_col_l
        col_r = settings.dashboard_col_r
        if settings.dashboard_auto_width:
            min_r = "J" if use_v5_main else col_r
            col_r = sa_writer.compute_col_r(col_l=col_l, needed_cols=max_cols, min_col_r=min_r)

        sent = 0
        if not dashboard_variants_only:
            if use_v5_main:
                # v5 主表：先将每张卡的原始表结构变换为 v5 统一表头（币种/字段/7周期）
                transformed: list[dict] = []
                for p in payloads:
                    table = p.get("table") or {}
                    cols = table.get("columns") or []
                    rows = table.get("rows") or []
                    if isinstance(cols, list) and isinstance(rows, list):
                        cols_s = [str(c) for c in cols if c is not None]
                        vt = field_rows_period_columns(columns=cols_s, rows=rows)
                        np = dict(p)
                        np["table"] = {"columns": vt.columns, "rows": vt.rows}
                        transformed.append(np)
                    else:
                        transformed.append(p)

                try:
                    sa_writer.write_dashboard_v5_main(payloads=transformed, col_l=col_l, col_r=col_r)
                    sent = len(transformed)
                except Exception as exc:
                    print(f"❌ 看板重绘失败（v5）{type(exc).__name__}: {exc}")
                    return 3
            else:
                # legacy：逐张卡写入（兼容“超宽字段分块纵向堆叠”）
                # dashboard 模式强制用 append（配合 reset），实现“紧凑排布、不卡槽位、不卡高度”
                sa_writer.set_dashboard_mode("append")
                sa_writer.reset_dashboard(col_l=col_l, col_r=col_r, compact=True)

                for p in payloads:
                    ok, status, body = _send_one(p)
                    if not ok:
                        print(f"❌ 看板重绘失败 status={status} body={json.dumps(body, ensure_ascii=False)}")
                        return 3
                    sent += 1

        if dashboard_variants or dashboard_variants_only:
            try:
                sa_writer.write_dashboard_variants(payloads=payloads, col_l=col_l, min_col_r="M")
            except Exception as exc:
                print(f"⚠️ 变体看板生成失败：{type(exc).__name__}: {exc}")

        # 统一时钟刷新（用户要求）：
        # - 关闭“币种查询/Polymarket 的独立 interval 节流”，每轮只按 daemon 的 tick 统一刷新一次
        # - 仍保留各功能 enable 开关（symbol_tabs_mode/pm_enable/pme_enable）
        unified_refresh = _env_bool("SHEETS_UNIFIED_REFRESH", "0")

        # 币种查询子表（4 个交易对）：覆盖写，不走 facts（默认每 15 分钟刷新一次，避免配额爆炸）
        if settings.symbol_tabs_mode != "none" and settings.symbol_tabs:
            now = int(time.time())
            meta = sa_writer.meta_get()
            try:
                last = int(str(meta.get("symbol_tabs_last_epoch") or "0").strip() or "0")
            except Exception:
                last = 0
            interval = int(settings.symbol_tabs_interval_seconds)
            should = bool(settings.force_render) or unified_refresh or interval <= 0 or (now - last) >= interval
            if should:
                errors: list[str] = []
                for sym in settings.symbol_tabs:
                    try:
                        tab_title = normalize_symbol_tab_title(symbol=sym, prefix=settings.symbol_tab_prefix)
                        sheet = export_symbol_query_sheet(symbol=sym, lang=lang)
                        sa_writer.write_symbol_query_tab(tab_title=tab_title, sheet=sheet)
                    except Exception as exc:
                        errors.append(f"{sym}:{type(exc).__name__}:{exc}")
                sa_writer.meta_set(
                    {
                        "symbol_tabs_last_epoch": str(now),
                        "symbol_tabs_last_error": ";".join(errors)[:2000],
                    }
                )

        # Polymarket 统计子表：默认 auto（配置了 ssh host 则走 ssh，否则本机运行 node）
        pm_enable = (os.environ.get("SHEETS_POLYMARKET_STATS_ENABLE", "1") or "1").strip().lower()
        if pm_enable in {"0", "off", "false", "no"}:
            pm_on = False
        elif pm_enable in {"1", "on", "true", "yes"}:
            pm_on = True
        else:
            # auto：默认启用（即使导出失败也会写入“错误卡片”，避免用户“看不到 tab”）
            pm_on = True
        if pm_on:
            now = int(time.time())
            meta = sa_writer.meta_get()
            try:
                last = int(str(meta.get("polymarket_stats_last_epoch") or "0").strip() or "0")
            except Exception:
                last = 0
            interval = int((os.environ.get("SHEETS_POLYMARKET_STATS_INTERVAL_SECONDS", "900") or "900").strip() or "900")
            should = bool(settings.force_render) or unified_refresh or interval <= 0 or (now - last) >= interval
            if should:
                tab_title = (os.environ.get("SHEETS_TAB_POLYMARKET_STATS", "Polymarket统计") or "Polymarket统计").strip()
                err = ""
                try:
                    pm_sheet = export_polymarket_stats_sheet(lang=lang)
                    sa_writer.write_polymarket_stats_tab(tab_title=tab_title, sheet=pm_sheet)
                except Exception as exc:
                    err = f"{type(exc).__name__}:{exc}"
                sa_writer.meta_set(
                    {
                        "polymarket_stats_last_epoch": str(now),
                        "polymarket_stats_last_error": (err or "")[:2000],
                    }
                )

        # Polymarket facts 事件子表：结构化事实（append-only 的长期源头）抽取为“最近 24h”可审计视图
        # 默认关闭：这是高频明细表，会造成表格负担与额外噪声；需要时再显式开启。
        pme_enable = (os.environ.get("SHEETS_POLYMARKET_FACTS_EVENTS_ENABLE", "0") or "0").strip().lower()
        if pme_enable not in {"0", "off", "false", "no"}:
            now = int(time.time())
            meta = sa_writer.meta_get()
            try:
                last = int(str(meta.get("polymarket_events_last_epoch") or "0").strip() or "0")
            except Exception:
                last = 0
            interval = int(
                (os.environ.get("SHEETS_POLYMARKET_FACTS_EVENTS_INTERVAL_SECONDS", "900") or "900").strip() or "900"
            )
            should = bool(settings.force_render) or unified_refresh or interval <= 0 or (now - last) >= interval
            if should:
                tab_title = (os.environ.get("SHEETS_TAB_POLYMARKET_EVENTS", "Polymarket事件") or "Polymarket事件").strip()
                err = ""
                try:
                    pm_sheet = export_polymarket_facts_events_sheet(lang=lang)
                    sa_writer.write_polymarket_stats_tab(tab_title=tab_title, sheet=pm_sheet)
                except Exception as exc:
                    err = f"{type(exc).__name__}:{exc}"
                sa_writer.meta_set(
                    {
                        "polymarket_events_last_epoch": str(now),
                        "polymarket_events_last_error": (err or "")[:2000],
                    }
                )

        if dashboard_variants_only:
            print(
                f"✅ 看板变体生成完成 mode=dashboard variants_only=1 cards={len(payloads)} col_l={col_l} col_r={col_r}"
            )
        else:
            print(f"✅ 看板重绘完成 mode=dashboard cards={sent} col_l={col_l} col_r={col_r}")
        return 0

    # snapshot/append 模式：outbox + 幂等（用于事实表或 slot 覆盖写）
    outbox = JsonlOutbox(settings.outbox_path, settings.checkpoint_path)
    idem = IdempotencyStore()

    def _flush_outbox() -> tuple[int, int] | None:
        sent = 0
        skipped = 0
        for item in outbox.iter_unsent():
            card_key = str((item.payload or {}).get("card_key") or "").strip()
            if (not settings.force_render) and card_key and idem.has(card_key):
                outbox.save_checkpoint(item.offset)
                skipped += 1
                continue

            ok, status, body = _send_one(item.payload)
            if not ok:
                print(f"❌ 写入失败 offset={item.offset} status={status} body={json.dumps(body, ensure_ascii=False)}")
                return None
            if card_key:
                idem.mark(card_key)
            outbox.save_checkpoint(item.offset)
            sent += 1
        return sent, skipped

    if not settings.dry_run:
        # 先 flush 旧积压，避免“限流/失败时仍不断 append 新 outbox”导致 outbox 无界增长。
        if _flush_outbox() is None:
            return 3

    exporter = TgCardsExporter(include_blacklist=settings.include_blacklist, lang=lang)
    results = await exporter.export(only_cards=only_cards)

    appended = 0
    skipped_append = 0
    for r in results:
        if r.event is None:
            continue
        payload = r.event.to_dict()
        card_key = str(payload.get("card_key") or "").strip()
        if (not settings.force_render) and card_key and idem.has(card_key):
            skipped_append += 1
            continue
        outbox.append(payload)
        appended += 1

    if settings.dry_run:
        print(f"[dry-run] appended={appended} skipped_append={skipped_append} outbox={settings.outbox_path}")
        return 0

    flushed = _flush_outbox()
    if flushed is None:
        return 3
    sent, skipped = flushed

    # snapshot 模式默认不刷新币种查询子表（否则每轮写入量过大，容易触发配额/超时）
    # 如需要可配置：SHEETS_SYMBOL_TABS_MODE=every
    if settings.write_mode == "sa" and settings.symbol_tabs_mode == "every" and settings.symbol_tabs:
        assert sa_writer is not None
        errors: list[str] = []
        for sym in settings.symbol_tabs:
            try:
                tab_title = normalize_symbol_tab_title(symbol=sym, prefix=settings.symbol_tab_prefix)
                sheet = export_symbol_query_sheet(symbol=sym, lang=lang)
                sa_writer.write_symbol_query_tab(tab_title=tab_title, sheet=sheet)
            except Exception as exc:
                errors.append(f"{sym}:{type(exc).__name__}:{exc}")
        if errors:
            try:
                sa_writer.meta_set({"symbol_tabs_last_error": ";".join(errors)[:2000]})
            except Exception:
                pass

    print(
        f"✅ flush 完成 appended={appended} skipped_append={skipped_append} sent={sent} skipped={skipped} checkpoint={outbox.load_checkpoint()} mode={settings.write_mode}"
    )
    return 0


def main() -> None:
    # 尝试加载全局 .env（不强制；服务启动脚本通常已 export）
    try:
        repo_root = find_repo_root(Path(__file__).resolve())
        env_path = repo_root / "assets" / "config" / ".env"
        if not env_path.exists():
            env_path = repo_root / "config" / ".env"
        if env_path.exists():
            load_dotenv(env_path, override=False)
    except Exception:
        # 允许在“非仓库根目录结构”下运行（例如单文件调试/容器内挂载结构不同），此时依赖外部 export 的环境变量。
        pass

    args = _parse_args()
    # .../services/consumption/sheets-service/src/__main__.py
    # parents[0]=src, parents[1]=sheets-service
    service_dir = Path(__file__).resolve().parents[1]
    settings = Settings.from_env(service_dir)

    if args.mock_webhook:
        secret = settings.webhook_secret or "dev-secret"
        data_dir = service_dir / "data" / "mock_webhook"
        data_dir.mkdir(parents=True, exist_ok=True)
        serve_mock_webhook(host="127.0.0.1", port=args.mock_port, secret=secret, data_dir=data_dir)
        return

    if args.write_mode.strip():
        settings = replace(settings, write_mode=args.write_mode.strip())

    if args.bootstrap:
        if settings.write_mode != "sa":
            print("❌ --bootstrap 仅支持 SA 模式：设置 SHEETS_WRITE_MODE=sa 或 --write-mode sa")
            sys.exit(2)
        writer = SaSheetsWriter(
            spreadsheet_id=settings.spreadsheet_id,
            credentials_path=settings.sa_credentials_path,
            dashboard_col_l=settings.dashboard_col_l,
            dashboard_col_r=settings.dashboard_col_r,
            dashboard_mode=settings.dashboard_mode,
            dashboard_slot_height=settings.dashboard_slot_height,
            facts_mode=settings.facts_mode,
            share_email=settings.share_email,
            public_read=settings.public_read,
            drive_folder_id=settings.drive_folder_id,
            blob_threshold_chars=settings.blob_threshold_chars,
            timeout_seconds=settings.webhook_timeout_seconds,
            schema_mode=settings.schema_mode,
            local_meta_path=settings.local_meta_path,
        )
        res = writer.bootstrap(title=args.bootstrap_title)
        print(
            json.dumps(
                {"ok": True, "spreadsheet_id": res.spreadsheet_id, "url": res.spreadsheet_url}, ensure_ascii=False
            )
        )
        sys.exit(0)

    if args.delete_tab.strip():
        if settings.write_mode != "sa":
            print("❌ --delete-tab 仅支持 SA 模式：设置 SHEETS_WRITE_MODE=sa 或 --write-mode sa")
            sys.exit(2)
        writer = SaSheetsWriter(
            spreadsheet_id=settings.spreadsheet_id,
            credentials_path=settings.sa_credentials_path,
            dashboard_col_l=settings.dashboard_col_l,
            dashboard_col_r=settings.dashboard_col_r,
            dashboard_mode=settings.dashboard_mode,
            dashboard_slot_height=settings.dashboard_slot_height,
            facts_mode=settings.facts_mode,
            share_email=settings.share_email,
            public_read=settings.public_read,
            drive_folder_id=settings.drive_folder_id,
            blob_threshold_chars=settings.blob_threshold_chars,
            timeout_seconds=settings.webhook_timeout_seconds,
            schema_mode=settings.schema_mode,
            local_meta_path=settings.local_meta_path,
        )
        try:
            title = args.delete_tab.strip()
            res = writer.delete_tab_if_exists(title=title)
            print(json.dumps({"ok": True, "op": "delete_tab", **res}, ensure_ascii=False))
            sys.exit(0)
        except Exception as exc:
            print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
            sys.exit(3)

    if args.reset_dashboard or args.rebuild_dashboard or args.prune_tabs:
        if settings.write_mode != "sa":
            print(
                "❌ --reset-dashboard/--rebuild-dashboard 仅支持 SA 模式：设置 SHEETS_WRITE_MODE=sa 或 --write-mode sa"
            )
            sys.exit(2)
        writer = SaSheetsWriter(
            spreadsheet_id=settings.spreadsheet_id,
            credentials_path=settings.sa_credentials_path,
            dashboard_col_l=settings.dashboard_col_l,
            dashboard_col_r=settings.dashboard_col_r,
            dashboard_mode=settings.dashboard_mode,
            dashboard_slot_height=settings.dashboard_slot_height,
            facts_mode=settings.facts_mode,
            share_email=settings.share_email,
            public_read=settings.public_read,
            drive_folder_id=settings.drive_folder_id,
            blob_threshold_chars=settings.blob_threshold_chars,
            timeout_seconds=settings.webhook_timeout_seconds,
            schema_mode=settings.schema_mode,
            local_meta_path=settings.local_meta_path,
        )
        try:
            if args.prune_tabs:
                keep_symbol_tabs = []
                for sym in settings.symbol_tabs:
                    keep_symbol_tabs.append(normalize_symbol_tab_title(symbol=sym, prefix=settings.symbol_tab_prefix))
                res = writer.prune_tabs(symbol_tab_prefix=settings.symbol_tab_prefix, keep_symbol_tabs=keep_symbol_tabs)
                print(json.dumps({"ok": True, "op": "prune_tabs", **res}, ensure_ascii=False))
                sys.exit(0)
            if args.reset_dashboard:
                res = writer.reset_dashboard(col_l=settings.dashboard_col_l, col_r=settings.dashboard_col_r)
                print(json.dumps({"ok": True, "op": "reset_dashboard", **res}, ensure_ascii=False))
                sys.exit(0)
            res = writer.rebuild_dashboard(max_cards=int(args.rebuild_max_cards or 0))
            print(json.dumps({"ok": True, "op": "rebuild_dashboard", **res}, ensure_ascii=False))
            sys.exit(0)
        except Exception as exc:
            print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
            sys.exit(3)

    if args.snapshot_polymarket_col_widths:
        if settings.write_mode != "sa":
            print("❌ --snapshot-polymarket-col-widths 仅支持 SA 模式：设置 SHEETS_WRITE_MODE=sa 或 --write-mode sa")
            sys.exit(2)
        writer = SaSheetsWriter(
            spreadsheet_id=settings.spreadsheet_id,
            credentials_path=settings.sa_credentials_path,
            dashboard_col_l=settings.dashboard_col_l,
            dashboard_col_r=settings.dashboard_col_r,
            dashboard_mode=settings.dashboard_mode,
            dashboard_slot_height=settings.dashboard_slot_height,
            facts_mode=settings.facts_mode,
            share_email=settings.share_email,
            public_read=settings.public_read,
            drive_folder_id=settings.drive_folder_id,
            blob_threshold_chars=settings.blob_threshold_chars,
            timeout_seconds=settings.webhook_timeout_seconds,
            schema_mode=settings.schema_mode,
            local_meta_path=settings.local_meta_path,
        )
        tab_top15 = (os.environ.get("SHEETS_TAB_POLYMARKET_TOP15", "PolymarketTop15") or "PolymarketTop15").strip()
        tab_timeslot = (os.environ.get("SHEETS_TAB_POLYMARKET_TIMESLOT", "Polymarket时段分布") or "Polymarket时段分布").strip()
        tab_category = (os.environ.get("SHEETS_TAB_POLYMARKET_CATEGORY", "Polymarket类别偏好") or "Polymarket类别偏好").strip()

        w_top15 = writer.snapshot_column_widths(tab_top15)
        w_timeslot = writer.snapshot_column_widths(tab_timeslot)
        w_category = writer.snapshot_column_widths(tab_category)

        print(f"SHEETS_POLYMARKET_FIXED_COL_WIDTHS_TOP15={','.join(str(x) for x in w_top15)}")
        print(f"SHEETS_POLYMARKET_FIXED_COL_WIDTHS_TIMESLOT={','.join(str(x) for x in w_timeslot)}")
        print(f"SHEETS_POLYMARKET_FIXED_COL_WIDTHS_CATEGORY={','.join(str(x) for x in w_category)}")
        sys.exit(0)

    if args.dry_run:
        settings = replace(settings, dry_run=True)
    if args.force:
        settings = replace(settings, force_render=True)

    only_cards = [c.strip() for c in (args.cards or settings.export_cards).split(",") if c.strip()] or None
    lang = (args.lang or settings.export_lang).strip() or "zh_CN"

    if args.daemon and args.once:
        print("❌ 不能同时指定 --daemon 和 --once")
        sys.exit(2)

    if args.daemon:
        while True:
            rc = asyncio.run(
                _run_once(
                    settings,
                    only_cards=only_cards,
                    lang=lang,
                    dashboard_variants=args.dashboard_variants,
                    dashboard_variants_only=args.dashboard_variants_only,
                )
            )
            if rc != 0:
                # daemon 模式失败：不退出，避免写入临时错误导致服务退出；由外层守护脚本管理
                print(f"⚠️ 本轮执行失败 rc={rc}，{settings.interval_seconds}s 后重试")
            time.sleep(max(settings.interval_seconds, 5))
    else:
        rc = asyncio.run(
            _run_once(
                settings,
                only_cards=only_cards,
                lang=lang,
                dashboard_variants=args.dashboard_variants,
                dashboard_variants_only=args.dashboard_variants_only,
            )
        )
        sys.exit(rc)


if __name__ == "__main__":
    main()
