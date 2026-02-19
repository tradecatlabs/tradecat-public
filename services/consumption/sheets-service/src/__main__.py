from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

from dotenv import load_dotenv

from src.config import Settings
from src.dashboard_dedup import inject_base_card_and_dedup
from src.idempotency import IdempotencyStore
from src.mock_webhook_server import serve_mock_webhook
from src.outbox import JsonlOutbox
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
    p.add_argument(
        "--prune-tabs",
        action="store_true",
        help="SA 模式：删除非必要 tab（仅保留 看板 + 配置的币种查询子表）",
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


async def _run_once(settings: Settings, *, only_cards: list[str] | None, lang: str) -> int:
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

        # dedup 可能新增/删除列：重算 max_cols，用于 auto width
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
        # dashboard 模式强制用 append（配合 reset），实现“紧凑排布、不卡槽位、不卡高度”
        sa_writer.set_dashboard_mode("append")

        # 自动宽度：避免“超宽表头纵向分块”让用户误以为列丢失
        col_l = settings.dashboard_col_l
        col_r = settings.dashboard_col_r
        if settings.dashboard_auto_width:
            col_r = sa_writer.compute_col_r(col_l=col_l, needed_cols=max_cols, min_col_r=col_r)

        sa_writer.reset_dashboard(col_l=col_l, col_r=col_r, compact=True)

        sent = 0
        for p in payloads:
            ok, status, body = _send_one(p)
            if not ok:
                print(f"❌ 看板重绘失败 status={status} body={json.dumps(body, ensure_ascii=False)}")
                return 3
            sent += 1

        # 币种查询子表（4 个交易对）：覆盖写，不走 facts（默认每 15 分钟刷新一次，避免配额爆炸）
        if settings.symbol_tabs_mode != "none" and settings.symbol_tabs:
            now = int(time.time())
            meta = sa_writer.meta_get()
            try:
                last = int(str(meta.get("symbol_tabs_last_epoch") or "0").strip() or "0")
            except Exception:
                last = 0
            interval = int(settings.symbol_tabs_interval_seconds)
            should = interval <= 0 or (now - last) >= interval
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

        print(f"✅ 看板重绘完成 mode=dashboard cards={sent} col_l={col_l} col_r={col_r}")
        return 0

    # snapshot/append 模式：outbox + 幂等（用于事实表或 slot 覆盖写）
    outbox = JsonlOutbox(settings.outbox_path, settings.checkpoint_path)
    idem = IdempotencyStore(settings.idempotency_db_path)

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
        load_dotenv(repo_root / "config" / ".env", override=False)
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
            rc = asyncio.run(_run_once(settings, only_cards=only_cards, lang=lang))
            if rc != 0:
                # daemon 模式失败：不退出，避免写入临时错误导致服务退出；由外层守护脚本管理
                print(f"⚠️ 本轮执行失败 rc={rc}，{settings.interval_seconds}s 后重试")
            time.sleep(max(settings.interval_seconds, 5))
    else:
        rc = asyncio.run(_run_once(settings, only_cards=only_cards, lang=lang))
        sys.exit(rc)


if __name__ == "__main__":
    main()
