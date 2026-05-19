from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from tradecat_auto.agent_market_context import (
    ALLOWED_ENDPOINTS_BY_FAMILY,
    ALLOWED_MODES,
    DEFAULT_SOURCE_MANIFEST,
    audit_agent_market_context,
    build_agent_market_context_from_public_bundle,
    build_paper_report_from_agent_market_context,
    load_agent_market_context,
)
from tradecat_auto.agent_research_cycle import (
    audit_agent_research_cycle,
    build_observe_only_drafts,
    build_observe_only_research_cycle,
    write_observe_only_drafts,
)
from tradecat_auto.agent_soft_layer import build_agent_soft_layer_bundle
from tradecat_auto.agent_trade_thesis import load_agent_trade_thesis
from tradecat_auto.audit_journal import append_audit_record, journal_summary, record_service_cycle
from tradecat_auto.binance_market import BinanceMarketClient, normalize_to_usdt_perp_symbol
from tradecat_auto.paper_autonomy import load_paper_autonomy_profile
from tradecat_auto.paper_costs import BINANCE_USDM_PUBLIC_TAKER_FEE_BPS, DEFAULT_PAPER_SLIPPAGE_BPS
from tradecat_auto.paper_ledger import (
    PaperLedgerError,
    apply_paper_execution,
    apply_position_management_thesis,
    load_paper_ledger,
    paper_account_state,
    paper_ledger_lock,
    paper_ledger_summary,
    save_paper_ledger,
)
from tradecat_auto.pipeline import build_paper_pipeline_report
from tradecat_auto.production_control import (
    DEFAULT_AUTO_PAPER_ARCHIVE_PATH,
    DEFAULT_AUTO_PAPER_JOURNAL_PATH,
    DEFAULT_AUTO_PAPER_LEDGER_PATH,
    DEFAULT_AUTO_PAPER_STATE_PATH,
    build_daily_report,
    build_health_report,
    build_latest_cycle_report,
    build_latest_decision_report,
    build_telegram_alerts,
)
from tradecat_auto.replay import build_replay_report
from tradecat_auto.risk import load_portfolio_risk_policy
from tradecat_auto.safety_boundary import paper_watch_report_flags, paper_watch_safety_boundary
from tradecat_auto.service import DEFAULT_STATE_PATH, run_service_cycle
from tradecat_auto.strategy_review import build_strategy_review_report, save_strategy_state
from tradecat_auto.tradecat_source import DEFAULT_TRADECAT_PUBLIC, TradeCatPublicSource, signal_events_payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TradeCat Auto public/read-only probes")
    sub = parser.add_subparsers(dest="command", required=True)

    universe = sub.add_parser("market-universe", help="Fetch Binance USDⓈ-M USDT perpetual universe")
    universe.add_argument("--base-url", default="https://fapi.binance.com")
    universe.add_argument("--json", action="store_true", help="Emit JSON")

    snapshot = sub.add_parser(
        "market-snapshot",
        help="Fetch batchable Binance public market endpoints once and filter by optional symbols",
    )
    snapshot.add_argument("--base-url", default="https://fapi.binance.com")
    snapshot.add_argument(
        "--symbols",
        default="",
        help="Comma/space separated symbols to filter, e.g. BTCUSDT,ETHUSDT; empty returns all endpoint rows",
    )
    snapshot.add_argument("--json", action="store_true", help="Emit JSON")

    bundle = sub.add_parser(
        "market-bundle",
        help="Fetch complete per-symbol Binance public market bundles with batchable requests merged",
    )
    bundle.add_argument("--base-url", default="https://fapi.binance.com")
    bundle.add_argument("--symbols", required=True, help="Comma/space separated symbols, e.g. BTCUSDT,ETHUSDT")
    bundle.add_argument("--period", default="5m")
    bundle.add_argument("--depth-limit", type=int, default=20)
    bundle.add_argument("--hist-limit", type=int, default=2)
    bundle.add_argument("--kline-limit", type=int, default=100)
    bundle.add_argument("--json", action="store_true", help="Emit JSON")

    agent_context = sub.add_parser(
        "agent-market-context",
        help="Fetch one symbol's complete Binance public bundle and emit agent_market_context.v1",
    )
    agent_context.add_argument("--base-url", default="https://fapi.binance.com")
    agent_context.add_argument("--symbol", required=True)
    agent_context.add_argument("--period", default="5m")
    agent_context.add_argument("--depth-limit", type=int, default=20)
    agent_context.add_argument("--hist-limit", type=int, default=2)
    agent_context.add_argument("--kline-limit", type=int, default=100)
    agent_context.add_argument("--agent", default="tradecat-public-agent-tool-runner")
    agent_context.add_argument("--output", default="", help="Optional JSON output path")
    agent_context.add_argument("--json", action="store_true", help="Emit JSON")

    probe = sub.add_parser("probe-public", help="Probe TradeCat public sheets and Binance public market endpoints")
    probe.add_argument("--tradecat-public", default=str(DEFAULT_TRADECAT_PUBLIC))
    probe.add_argument("--base-url", default="https://fapi.binance.com")
    probe.add_argument("--symbol", default="auto", help="Symbol to probe, or auto to use first anomaly candidate")
    probe.add_argument("--event-limit", type=int, default=0, help="Signal-flow rows to read; 0 means no limit")
    probe.add_argument("--anomaly-limit", type=int, default=0)
    probe.add_argument("--json", action="store_true", help="Emit JSON")

    run_once = sub.add_parser("run-once", help="Run one public-readonly analysis cycle and paper simulation")
    run_once.add_argument("--tradecat-public", default=str(DEFAULT_TRADECAT_PUBLIC))
    run_once.add_argument("--base-url", default="https://fapi.binance.com")
    run_once.add_argument("--symbol", default="auto", help="Symbol to run, or auto to use first anomaly candidate")
    run_once.add_argument("--mode", choices=["paper", "watch", "mainnet"], default="paper")
    run_once.add_argument(
        "--notional-usdt", type=float, default=None, help="Explicit effective paper notional; no default"
    )
    run_once.add_argument(
        "--agent-margin-usdt", type=float, default=None, help="Agent-decided paper margin; no default"
    )
    run_once.add_argument("--paper-leverage", type=float, default=None, help="Agent-decided paper leverage; no default")
    run_once.add_argument(
        "--paper-margin-budget-usdt",
        type=float,
        default=None,
        help="Optional paper margin cap; omitted means no cap and no default order amount",
    )
    run_once.add_argument(
        "--agent-trade-thesis-path",
        default="",
        help="Optional Agent trade thesis JSON for paper/watch sizing and exits",
    )
    run_once.add_argument(
        "--paper-autonomy-profile-path",
        default="",
        help="Optional local paper autonomy profile JSON for Agent-delegated paper sizing/exits",
    )
    run_once.add_argument(
        "--portfolio-risk-policy-path", default="", help="Optional paper/watch portfolio risk policy JSON"
    )
    run_once.add_argument(
        "--paper-kill-switch-path",
        default="",
        help="Optional local file path; if present, new paper entries are rejected",
    )
    run_once.add_argument("--event-limit", type=int, default=0, help="Signal-flow rows to read; 0 means no limit")
    run_once.add_argument("--anomaly-limit", type=int, default=0)
    run_once.add_argument("--json", action="store_true", help="Emit JSON")

    run_loop = sub.add_parser("run-loop", help="Run a safe polling loop around public-readonly paper cycles")
    run_loop.add_argument("--tradecat-public", default=str(DEFAULT_TRADECAT_PUBLIC))
    run_loop.add_argument("--base-url", default="https://fapi.binance.com")
    run_loop.add_argument("--symbol", default="auto", help="Symbol to run, or auto to use first anomaly candidate")
    run_loop.add_argument("--mode", choices=["paper", "watch"], default="paper")
    run_loop.add_argument(
        "--notional-usdt", type=float, default=None, help="Explicit effective paper notional; no default"
    )
    run_loop.add_argument(
        "--agent-margin-usdt", type=float, default=None, help="Agent-decided paper margin; no default"
    )
    run_loop.add_argument("--paper-leverage", type=float, default=None, help="Agent-decided paper leverage; no default")
    run_loop.add_argument(
        "--paper-margin-budget-usdt",
        type=float,
        default=None,
        help="Optional paper margin cap; omitted means no cap and no default order amount",
    )
    run_loop.add_argument(
        "--agent-trade-thesis-path",
        default="",
        help="Optional Agent trade thesis JSON for paper/watch sizing and exits",
    )
    run_loop.add_argument(
        "--paper-autonomy-profile-path",
        default="",
        help="Optional local paper autonomy profile JSON for Agent-delegated paper sizing/exits",
    )
    run_loop.add_argument(
        "--portfolio-risk-policy-path", default="", help="Optional paper/watch portfolio risk policy JSON"
    )
    run_loop.add_argument(
        "--paper-kill-switch-path",
        default="",
        help="Optional local file path; if present, new paper entries are rejected",
    )
    run_loop.add_argument(
        "--strategy-state-path",
        default="",
        help="Optional local strategy_state.v1 JSON produced by strategy-review",
    )
    run_loop.add_argument("--event-limit", type=int, default=0, help="Signal-flow rows to read; 0 means no limit")
    run_loop.add_argument("--anomaly-limit", type=int, default=0)
    run_loop.add_argument("--state-path", default=str(DEFAULT_STATE_PATH))
    run_loop.add_argument("--ledger-path", default="", help="Optional persistent paper ledger JSON path")
    run_loop.add_argument(
        "--archive-path", default="", help="Optional JSONL path for full service-cycle replay records"
    )
    run_loop.add_argument(
        "--journal-path",
        default="",
        help="Optional SQLite audit journal path for run/config/decision/order/fill records",
    )
    run_loop.add_argument("--initial-balance-usdt", type=float, default=1000.0)
    run_loop.add_argument("--paper-fee-bps", type=float, default=BINANCE_USDM_PUBLIC_TAKER_FEE_BPS)
    run_loop.add_argument("--paper-slippage-bps", type=float, default=DEFAULT_PAPER_SLIPPAGE_BPS)
    run_loop.add_argument(
        "--paper-max-holding-minutes",
        type=float,
        default=0.0,
        help="Deprecated status/config field; paper time stops require Agent/strategy max_holding_minutes",
    )
    run_loop.add_argument("--interval-seconds", type=float, default=60.0)
    run_loop.add_argument(
        "--maintenance-interval-seconds",
        type=float,
        default=300.0,
        help="Run ledger/health maintenance after this many seconds without fresh input; 0 disables",
    )
    run_loop.add_argument(
        "--max-cycles", type=int, default=0, help="Stop after N cycles; 0 means run until interrupted"
    )
    run_loop.add_argument("--once", action="store_true", help="Run exactly one service cycle and exit")
    run_loop.add_argument(
        "--max-event-age-seconds",
        type=float,
        default=None,
        help="Optional stale-signal cap; omitted means Agent/TradeCat can evaluate any fetched signal age",
    )
    run_loop.add_argument("--json", action="store_true", help="Emit JSON")

    paper = sub.add_parser("paper-report", help="Summarize the persistent auto-paper ledger")
    paper.add_argument("--ledger-path", default=str(DEFAULT_AUTO_PAPER_LEDGER_PATH))
    paper.add_argument("--initial-balance-usdt", type=float, default=1000.0)
    paper.add_argument(
        "--detail-limit",
        type=int,
        default=20,
        help="Maximum open positions / tail rows to include in the JSON report; 0 includes all local ledger details.",
    )
    paper.add_argument("--json", action="store_true", help="Emit JSON")

    strategy_review = sub.add_parser(
        "strategy-review",
        help="Review local paper outcomes and optionally write strategy_state.v1 runtime filters",
    )
    strategy_review.add_argument("--ledger-path", default=str(DEFAULT_AUTO_PAPER_LEDGER_PATH))
    strategy_review.add_argument("--archive-path", default=str(DEFAULT_AUTO_PAPER_ARCHIVE_PATH))
    strategy_review.add_argument("--output-state-path", default="", help="Optional strategy_state.v1 output path")
    strategy_review.add_argument("--min-closed-positions", type=int, default=50)
    strategy_review.add_argument("--min-symbol-trades", type=int, default=5)
    strategy_review.add_argument("--symbol-loss-usdt", type=float, default=0.75)
    strategy_review.add_argument("--symbol-win-rate-below", type=float, default=0.35)
    strategy_review.add_argument("--min-signal-type-trades", type=int, default=20)
    strategy_review.add_argument("--signal-type-loss-usdt", type=float, default=2.0)
    strategy_review.add_argument("--signal-type-win-rate-below", type=float, default=0.38)
    strategy_review.add_argument("--min-side-trades", type=int, default=100)
    strategy_review.add_argument("--side-loss-usdt", type=float, default=10.0)
    strategy_review.add_argument("--side-win-rate-below", type=float, default=0.38)
    strategy_review.add_argument("--max-open-positions", type=int, default=50)
    strategy_review.add_argument("--max-positions-per-symbol", type=int, default=3)
    strategy_review.add_argument("--json", action="store_true", help="Emit JSON")

    position_manage = sub.add_parser(
        "position-manage", help="Apply an Agent position-management thesis to the local paper ledger"
    )
    position_manage.add_argument("--thesis-path", required=True, help="Path to position_management_thesis.v1 JSON")
    position_manage.add_argument("--ledger-path", default=".runtime/auto-paper/paper_ledger.json")
    position_manage.add_argument(
        "--journal-path",
        default=".runtime/auto-paper/paper_audit.sqlite3",
        help="Optional SQLite audit journal path; empty disables journal write",
    )
    position_manage.add_argument("--initial-balance-usdt", type=float, default=1000.0)
    position_manage.add_argument("--paper-fee-bps", type=float, default=BINANCE_USDM_PUBLIC_TAKER_FEE_BPS)
    position_manage.add_argument("--paper-slippage-bps", type=float, default=DEFAULT_PAPER_SLIPPAGE_BPS)
    position_manage.add_argument("--now", default="", help="Optional ISO timestamp for deterministic tests")
    position_manage.add_argument("--json", action="store_true", help="Emit JSON")

    soft_layer = sub.add_parser("soft-layer", help="Show self-contained Agent soft prompt/policy bundle")
    soft_layer.add_argument(
        "--no-prompt-text", action="store_true", help="List prompt paths without embedding template text"
    )
    soft_layer.add_argument("--json", action="store_true", help="Emit JSON")

    research_cycle = sub.add_parser("research-cycle", help="Build an observe-only Agent research-cycle task")
    research_cycle.add_argument("--tradecat-public", default=str(DEFAULT_TRADECAT_PUBLIC))
    research_cycle.add_argument(
        "--symbol", default="auto", help="Symbol to research, or auto to use first anomaly candidate"
    )
    research_cycle.add_argument("--event-limit", type=int, default=0, help="Signal-flow rows to read; 0 means no limit")
    research_cycle.add_argument("--anomaly-limit", type=int, default=0)
    research_cycle.add_argument(
        "--output-dir", default="", help="Optional isolated directory for observe-only draft JSON outputs"
    )
    research_cycle.add_argument("--json", action="store_true", help="Emit JSON")

    context_audit = sub.add_parser("context-audit", help="Audit Agent-supplied public/read-only market context JSON")
    context_audit.add_argument("--input", required=True, help="Path to agent market context JSON")
    context_audit.add_argument("--json", action="store_true", help="Emit JSON")

    run_context = sub.add_parser("run-context", help="Run paper/watch pipeline from Agent-supplied market context JSON")
    run_context.add_argument("--input", required=True, help="Path to agent market context JSON")
    run_context.add_argument("--mode", choices=["paper", "watch", "mainnet"], default="paper")
    run_context.add_argument(
        "--notional-usdt", type=float, default=None, help="Explicit effective paper notional override; no default"
    )
    run_context.add_argument(
        "--agent-margin-usdt", type=float, default=None, help="Agent-decided paper margin override; no default"
    )
    run_context.add_argument(
        "--paper-leverage", type=float, default=None, help="Agent-decided paper leverage override; no default"
    )
    run_context.add_argument(
        "--paper-margin-budget-usdt",
        type=float,
        default=None,
        help="Optional paper margin cap; omitted means no cap and no default order amount",
    )
    run_context.add_argument(
        "--portfolio-risk-policy-path", default="", help="Optional paper/watch portfolio risk policy JSON"
    )
    run_context.add_argument(
        "--paper-kill-switch-path",
        default="",
        help="Optional local file path; if present, new paper entries are rejected",
    )
    run_context.add_argument(
        "--ledger-path",
        default=str(DEFAULT_AUTO_PAPER_LEDGER_PATH),
        help="Local paper ledger JSON path; empty disables run-context ledger write",
    )
    run_context.add_argument(
        "--archive-path",
        default=str(DEFAULT_AUTO_PAPER_ARCHIVE_PATH),
        help="Local JSONL service-cycle archive path; empty disables archive write",
    )
    run_context.add_argument(
        "--journal-path",
        default=str(DEFAULT_AUTO_PAPER_JOURNAL_PATH),
        help="Local SQLite audit journal path; empty disables journal write",
    )
    run_context.add_argument("--initial-balance-usdt", type=float, default=1000.0)
    run_context.add_argument("--paper-fee-bps", type=float, default=BINANCE_USDM_PUBLIC_TAKER_FEE_BPS)
    run_context.add_argument("--paper-slippage-bps", type=float, default=DEFAULT_PAPER_SLIPPAGE_BPS)
    run_context.add_argument("--now", default="", help="Optional ISO timestamp for deterministic runtime writes")
    run_context.add_argument("--json", action="store_true", help="Emit JSON")

    replay = sub.add_parser(
        "replay-report", help="Build a reproducible replay/backtest report from service-cycle archive and paper ledger"
    )
    replay.add_argument("--archive-path", default=str(DEFAULT_AUTO_PAPER_ARCHIVE_PATH))
    replay.add_argument("--ledger-path", default=str(DEFAULT_AUTO_PAPER_LEDGER_PATH))
    replay.add_argument(
        "--journal-path", default="", help="Optional local SQLite audit journal path for decision trace metadata"
    )
    replay.add_argument(
        "--generated-at", default="", help="Optional fixed report timestamp for deterministic replay tests"
    )
    replay.add_argument("--json", action="store_true", help="Emit JSON")

    audit_journal = sub.add_parser("audit-journal", help="Summarize the local SQLite append-only audit journal")
    audit_journal.add_argument("--journal-path", default=str(DEFAULT_AUTO_PAPER_JOURNAL_PATH))
    audit_journal.add_argument("--json", action="store_true", help="Emit JSON")

    latest_cycle = sub.add_parser("latest-cycle", help="Show the latest auto-paper service cycle from JSONL archive")
    latest_cycle.add_argument("--archive-path", default=str(DEFAULT_AUTO_PAPER_ARCHIVE_PATH))
    latest_cycle.add_argument("--json", action="store_true", help="Emit JSON")

    latest_decision = sub.add_parser(
        "latest-decision", help="Show the latest auditable Agent/TradeCat decision text from JSONL archive"
    )
    latest_decision.add_argument("--archive-path", default=str(DEFAULT_AUTO_PAPER_ARCHIVE_PATH))
    latest_decision.add_argument("--json", action="store_true", help="Emit JSON")

    health = sub.add_parser(
        "health-report", help="Summarize production heartbeat, ledger, cycle archive, and audit journal"
    )
    health.add_argument("--state-path", default=str(DEFAULT_AUTO_PAPER_STATE_PATH))
    health.add_argument("--ledger-path", default=str(DEFAULT_AUTO_PAPER_LEDGER_PATH))
    health.add_argument("--archive-path", default=str(DEFAULT_AUTO_PAPER_ARCHIVE_PATH))
    health.add_argument("--journal-path", default=str(DEFAULT_AUTO_PAPER_JOURNAL_PATH))
    health.add_argument("--now", default="", help="Optional ISO timestamp for deterministic checks")
    health.add_argument("--max-heartbeat-age-seconds", type=float, default=180.0)
    health.add_argument("--json", action="store_true", help="Emit JSON")

    daily = sub.add_parser("daily-report", help="Build a daily paper production report from ledger and cycle archive")
    daily.add_argument("--ledger-path", default=str(DEFAULT_AUTO_PAPER_LEDGER_PATH))
    daily.add_argument("--archive-path", default=str(DEFAULT_AUTO_PAPER_ARCHIVE_PATH))
    daily.add_argument("--date", default="", help="Report date YYYY-MM-DD; defaults to today")
    daily.add_argument("--json", action="store_true", help="Emit JSON")

    alerts = sub.add_parser("alert-payload", help="Build Telegram-friendly alert payload from health or daily report")
    alerts.add_argument("--kind", choices=["health", "daily"], default="health")
    alerts.add_argument("--state-path", default=str(DEFAULT_AUTO_PAPER_STATE_PATH))
    alerts.add_argument("--ledger-path", default=str(DEFAULT_AUTO_PAPER_LEDGER_PATH))
    alerts.add_argument("--archive-path", default=str(DEFAULT_AUTO_PAPER_ARCHIVE_PATH))
    alerts.add_argument("--journal-path", default=str(DEFAULT_AUTO_PAPER_JOURNAL_PATH))
    alerts.add_argument("--date", default="", help="Daily report date YYYY-MM-DD; defaults to today")
    alerts.add_argument("--now", default="", help="Optional ISO timestamp for deterministic health checks")
    alerts.add_argument("--max-heartbeat-age-seconds", type=float, default=180.0)
    alerts.add_argument("--json", action="store_true", help="Emit JSON")

    return parser


def exit_code_for_payload(command: str, payload: dict[str, Any]) -> int:
    """Map command payloads to process exit status.

    A user-systemd timer should stay healthy when a poll cycle simply has no
    fresh source event yet. Real run-loop errors still return a failing status.
    """

    if payload.get("ok") is True:
        return 0
    if command == "run-loop" and payload.get("action") == "SKIPPED_NO_EVENT":
        return 0
    return 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "market-universe":
        payload = market_universe_report(args)
        _print(payload, as_json=args.json)
        return exit_code_for_payload(args.command, payload)
    if args.command == "market-snapshot":
        payload = market_snapshot_report(args)
        _print(payload, as_json=args.json)
        return exit_code_for_payload(args.command, payload)
    if args.command == "market-bundle":
        payload = market_bundle_report(args)
        _print(payload, as_json=args.json)
        return exit_code_for_payload(args.command, payload)
    if args.command == "agent-market-context":
        payload = agent_market_context_report(args)
        _print(payload, as_json=args.json)
        return exit_code_for_payload(args.command, payload)
    if args.command == "probe-public":
        payload = probe_public(args)
        _print(payload, as_json=args.json)
        return exit_code_for_payload(args.command, payload)
    if args.command == "run-once":
        payload = run_once_public(args)
        _print(payload, as_json=args.json)
        return exit_code_for_payload(args.command, payload)
    if args.command == "run-loop":
        payload = run_loop_public(args)
        _print(payload, as_json=args.json)
        return exit_code_for_payload(args.command, payload)
    if args.command == "paper-report":
        payload = paper_report(args)
        _print(payload, as_json=args.json)
        return exit_code_for_payload(args.command, payload)
    if args.command == "strategy-review":
        payload = strategy_review_report(args)
        _print(payload, as_json=args.json)
        return exit_code_for_payload(args.command, payload)
    if args.command == "position-manage":
        payload = position_manage_report(args)
        _print(payload, as_json=args.json)
        return exit_code_for_payload(args.command, payload)
    if args.command == "soft-layer":
        payload = soft_layer_report(args)
        _print(payload, as_json=args.json)
        return exit_code_for_payload(args.command, payload)
    if args.command == "research-cycle":
        payload = research_cycle_report(args)
        _print(payload, as_json=args.json)
        return exit_code_for_payload(args.command, payload)
    if args.command == "context-audit":
        payload = context_audit_report(args)
        _print(payload, as_json=args.json)
        return exit_code_for_payload(args.command, payload)
    if args.command == "run-context":
        payload = run_context_public(args)
        _print(payload, as_json=args.json)
        return exit_code_for_payload(args.command, payload)
    if args.command == "replay-report":
        payload = replay_report(args)
        _print(payload, as_json=args.json)
        return exit_code_for_payload(args.command, payload)
    if args.command == "audit-journal":
        payload = audit_journal_report(args)
        _print(payload, as_json=args.json)
        return exit_code_for_payload(args.command, payload)
    if args.command == "latest-cycle":
        payload = latest_cycle_report(args)
        _print(payload, as_json=args.json)
        return exit_code_for_payload(args.command, payload)
    if args.command == "latest-decision":
        payload = latest_decision_report(args)
        _print(payload, as_json=args.json)
        return exit_code_for_payload(args.command, payload)
    if args.command == "health-report":
        payload = health_report(args)
        _print(payload, as_json=args.json)
        return exit_code_for_payload(args.command, payload)
    if args.command == "daily-report":
        payload = daily_report(args)
        _print(payload, as_json=args.json)
        return exit_code_for_payload(args.command, payload)
    if args.command == "alert-payload":
        payload = alert_payload_report(args)
        _print(payload, as_json=args.json)
        return exit_code_for_payload(args.command, payload)
    raise AssertionError(args.command)


def market_universe_report(args: argparse.Namespace) -> dict[str, Any]:
    client = BinanceMarketClient(base_url=args.base_url)
    try:
        payload = client.market_universe()
    except Exception as exc:
        return _market_universe_error_payload(args.base_url, exc, client)
    if not isinstance(payload, dict):
        return _market_universe_error_payload(
            args.base_url, TypeError("market_universe returned non-object result"), client
        )
    return payload


def market_snapshot_report(args: argparse.Namespace) -> dict[str, Any]:
    client = BinanceMarketClient(base_url=args.base_url)
    try:
        payload = client.fetch_public_market_snapshot(_parse_symbols_arg(getattr(args, "symbols", "")))
    except Exception as exc:
        return {
            "schema": "tradecat_auto.public_market_snapshot.v1",
            "schema_version": "1.0.0",
            "ok": False,
            "error_code": "public_market_snapshot_failed",
            **paper_watch_report_flags(),
            "base_url": args.base_url,
            "symbols": _parse_symbols_arg(getattr(args, "symbols", "")),
            "errors": {"market_snapshot": _format_exception(exc)},
            "provenance": {"source": "tradecat_auto.cli.market_snapshot_report"},
            "safety": _safety_boundary(),
        }
    return payload if isinstance(payload, dict) else _market_snapshot_non_object_payload(args)


def market_bundle_report(args: argparse.Namespace) -> dict[str, Any]:
    client = BinanceMarketClient(base_url=args.base_url)
    symbols = _parse_symbols_arg(getattr(args, "symbols", ""))
    if not symbols:
        return {
            "schema": "tradecat_auto.public_market_bundle_batch.v1",
            "schema_version": "1.0.0",
            "ok": False,
            "error_code": "public_market_bundle_symbols_required",
            **paper_watch_report_flags(),
            "base_url": args.base_url,
            "symbols": [],
            "errors": {"symbols": "at least one symbol is required"},
            "provenance": {"source": "tradecat_auto.cli.market_bundle_report"},
            "safety": _safety_boundary(),
        }
    try:
        payload = client.fetch_public_market_bundles(
            symbols,
            period=str(getattr(args, "period", "5m") or "5m"),
            depth_limit=int(getattr(args, "depth_limit", 20) or 20),
            hist_limit=int(getattr(args, "hist_limit", 2) or 2),
            kline_limit=int(getattr(args, "kline_limit", 100) or 100),
        )
    except Exception as exc:
        return {
            "schema": "tradecat_auto.public_market_bundle_batch.v1",
            "schema_version": "1.0.0",
            "ok": False,
            "error_code": "public_market_bundle_batch_failed",
            **paper_watch_report_flags(),
            "base_url": args.base_url,
            "symbols": symbols,
            "errors": {"market_bundle": _format_exception(exc)},
            "provenance": {"source": "tradecat_auto.cli.market_bundle_report"},
            "safety": _safety_boundary(),
        }
    return payload if isinstance(payload, dict) else _market_bundle_non_object_payload(args, symbols)


def agent_market_context_report(args: argparse.Namespace) -> dict[str, Any]:
    client = BinanceMarketClient(base_url=args.base_url)
    symbol = str(args.symbol or "").upper().strip()
    if symbol and not symbol.endswith("USDT"):
        symbol = f"{symbol}USDT"
    try:
        bundle = client.fetch_public_market_bundle(
            symbol,
            period=str(getattr(args, "period", "5m") or "5m"),
            depth_limit=int(getattr(args, "depth_limit", 20) or 20),
            hist_limit=int(getattr(args, "hist_limit", 2) or 2),
            kline_limit=int(getattr(args, "kline_limit", 100) or 100),
        )
    except Exception as exc:
        return {
            "schema": "tradecat_auto.agent_market_context.v1",
            "schema_version": "1.0.0",
            "ok": False,
            "symbol": symbol.upper().strip(),
            "mode": "public_readonly",
            "error_code": "agent_market_context_public_bundle_failed",
            "error": {
                "code": "agent_market_context_public_bundle_failed",
                "kind": "public_readonly_market_data",
                "message": _format_exception(exc),
                "retryable": True,
            },
            "provenance": {
                "agent": str(getattr(args, "agent", "") or "tradecat-public-agent-tool-runner"),
                "source": "tradecat_auto.cli.agent_market_context_report",
                "source_manifest": DEFAULT_SOURCE_MANIFEST,
            },
            "market_data": [],
            "safety": _safety_boundary(),
        }
    context = build_agent_market_context_from_public_bundle(
        bundle,
        agent=str(getattr(args, "agent", "") or "tradecat-public-agent-tool-runner"),
    )
    output = str(getattr(args, "output", "") or "").strip()
    if output:
        try:
            out_path = Path(output)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(context, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except OSError as exc:
            context["ok"] = False
            context["error_code"] = "agent_market_context_write_failed"
            context["error"] = {
                "code": "agent_market_context_write_failed",
                "kind": "local_io",
                "message": _format_exception(exc),
                "retryable": False,
            }
        else:
            context["output_path"] = output
    return context


def _market_snapshot_non_object_payload(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "schema": "tradecat_auto.public_market_snapshot.v1",
        "schema_version": "1.0.0",
        "ok": False,
        "error_code": "public_market_snapshot_failed",
        **paper_watch_report_flags(),
        "base_url": args.base_url,
        "symbols": _parse_symbols_arg(getattr(args, "symbols", "")),
        "errors": {"market_snapshot": "fetch_public_market_snapshot returned non-object result"},
        "provenance": {"source": "tradecat_auto.cli.market_snapshot_report"},
        "safety": _safety_boundary(),
    }


def _market_bundle_non_object_payload(args: argparse.Namespace, symbols: list[str]) -> dict[str, Any]:
    return {
        "schema": "tradecat_auto.public_market_bundle_batch.v1",
        "schema_version": "1.0.0",
        "ok": False,
        "error_code": "public_market_bundle_batch_failed",
        **paper_watch_report_flags(),
        "base_url": args.base_url,
        "symbols": symbols,
        "errors": {"market_bundle": "fetch_public_market_bundles returned non-object result"},
        "provenance": {"source": "tradecat_auto.cli.market_bundle_report"},
        "safety": _safety_boundary(),
    }


def _market_universe_error_payload(base_url: str, exc: Exception, client: Any) -> dict[str, Any]:
    return {
        "schema": "tradecat_auto.market_universe.v1",
        "schema_version": "1.0.0",
        "ok": False,
        **paper_watch_report_flags(),
        "base_url": base_url,
        "symbol_count": 0,
        "symbols": [],
        "rate_limits": [],
        "api_usage": _safe_api_usage(client),
        "error_code": "market_universe_failed",
        "error": _format_exception(exc),
        "provenance": {"source": "binance_usdm_public_exchange_info", "endpoint": "/fapi/v1/exchangeInfo"},
        "safety": _safety_boundary(),
    }


def _safe_api_usage(client: Any) -> dict[str, Any]:
    api_usage = getattr(client, "api_usage", None)
    if not callable(api_usage):
        return {}
    try:
        usage = api_usage()
    except Exception:
        return {}
    return usage if isinstance(usage, dict) else {}


def probe_public(args: argparse.Namespace) -> dict[str, Any]:
    client = BinanceMarketClient(base_url=args.base_url)
    source = TradeCatPublicSource(Path(args.tradecat_public))

    universe = _safe_call(client.market_universe)
    tradable = set(universe.get("symbols") or []) if universe.get("ok") else set()
    anomaly = _safe_call(source.fetch_anomaly_symbols, tradable_symbols=tradable, limit=args.anomaly_limit)
    signal_flow = _fetch_signal_flow_events(source, tradable, limit=getattr(args, "event_limit", 20))
    selected_symbol = _select_symbol(args.symbol, tradable, anomaly, signal_flow)
    events = signal_events_payload(signal_flow, anomaly, selected_symbol=selected_symbol)
    market_bundle = (
        _safe_call(client.fetch_public_market_bundle, selected_symbol)
        if selected_symbol
        else {
            "schema": "tradecat_auto.public_market_bundle.v1",
            "schema_version": "1.0.0",
            "ok": False,
            "error_code": "no_symbol_selected",
            **paper_watch_report_flags(),
            "errors": {"symbol": "no tradable symbol selected"},
            "provenance": {"source": "tradecat_auto.cli.probe_public", "selected_symbol": ""},
            "safety": _safety_boundary(),
        }
    )
    ok = bool(universe.get("ok") and events.get("ok") and anomaly.get("ok") and market_bundle.get("ok"))
    return {
        "schema": "tradecat_auto.public_probe.v1",
        "schema_version": "1.0.0",
        "ok": ok,
        **paper_watch_report_flags(),
        "error_code": None if ok else "public_probe_failed",
        "mode": "public_readonly_no_credentials_no_orders",
        "tradecat_public": str(Path(args.tradecat_public)),
        "binance_base_url": args.base_url,
        "selected_symbol": selected_symbol,
        "universe": _summarize_universe(universe),
        "events": {
            "ok": events.get("ok"),
            "source_dataset_key": events.get("source_dataset_key"),
            "count": len(events.get("events") or []),
            "latest": (events.get("events") or [None])[0],
        },
        "anomaly_symbols": {
            "ok": anomaly.get("ok"),
            "count": len(anomaly.get("symbols") or []),
            "row_count": len(anomaly.get("rows") or anomaly.get("symbols") or []),
            "sections": anomaly.get("sections") or [],
            "first_10": (anomaly.get("symbols") or [])[:10],
            "first_10_rows": (anomaly.get("rows") or anomaly.get("symbols") or [])[:10],
            "rejected_count": len(anomaly.get("rejected") or []),
        },
        "signal_flow_events": {
            "ok": signal_flow.get("ok"),
            "count": len(signal_flow.get("events") or []),
            "first_10": (signal_flow.get("events") or [])[:10],
            "rejected_count": len(signal_flow.get("rejected") or []),
            "duplicate_count": signal_flow.get("duplicate_count") or len(signal_flow.get("duplicates") or []),
        },
        "market_bundle": _summarize_market_bundle(market_bundle),
        "raw_errors": _collect_errors(universe, signal_flow, events, anomaly, market_bundle),
        "provenance": {
            "source": "tradecat_auto.cli.probe_public",
            "tradecat_public": str(Path(args.tradecat_public)),
            "binance_base_url": args.base_url,
            "selected_symbol": selected_symbol,
        },
        "safety": _safety_boundary(),
    }


def run_once_public(
    args: argparse.Namespace, *, client: Any | None = None, source: Any | None = None
) -> dict[str, Any]:
    try:
        agent_trade_thesis = _agent_trade_thesis_from_args(args)
    except ValueError as exc:
        return _agent_trade_thesis_load_failed_payload(args, "tradecat_auto.cli.run_once_public", exc)
    try:
        paper_autonomy_profile = _paper_autonomy_profile_from_args(args)
    except ValueError as exc:
        return _paper_autonomy_profile_load_failed_payload(args, "tradecat_auto.cli.run_once_public", exc)
    market_client = client or BinanceMarketClient(base_url=args.base_url)
    tradecat_source = source or TradeCatPublicSource(Path(args.tradecat_public))
    universe = _safe_call(market_client.market_universe)
    tradable = set(universe.get("symbols") or []) if universe.get("ok") else set()
    anomaly = _safe_call(tradecat_source.fetch_anomaly_symbols, tradable_symbols=tradable, limit=args.anomaly_limit)
    signal_flow = _fetch_signal_flow_events(tradecat_source, tradable, limit=getattr(args, "event_limit", 20))
    selected_symbol = _select_symbol(args.symbol, tradable, anomaly, signal_flow)
    events = signal_events_payload(signal_flow, anomaly, selected_symbol=selected_symbol)
    market_bundle = (
        _safe_call(market_client.fetch_public_market_bundle, selected_symbol)
        if selected_symbol
        else {
            "schema": "tradecat_auto.public_market_bundle.v1",
            "schema_version": "1.0.0",
            "ok": False,
            "error_code": "no_symbol_selected",
            **paper_watch_report_flags(),
            "errors": {"symbol": "no tradable symbol selected"},
            "provenance": {"source": "tradecat_auto.cli.run_once_public", "selected_symbol": ""},
            "safety": _safety_boundary(),
        }
    )
    if not selected_symbol:
        return {
            "schema": "tradecat_auto.run_once_report.v1",
            "schema_version": "1.0.0",
            "ok": False,
            **paper_watch_report_flags(),
            "mode": args.mode,
            "selected_symbol": "",
            "error_code": "no_symbol_selected",
            "error": "no_symbol_selected",
            "universe": _summarize_universe(universe),
            "raw_errors": _collect_errors(universe, signal_flow, events, anomaly, market_bundle),
            "provenance": {
                "source": "tradecat_auto.cli.run_once_public",
                "tradecat_public": str(Path(getattr(args, "tradecat_public", ""))),
                "binance_base_url": str(getattr(args, "base_url", "")),
                "selected_symbol": "",
            },
            "safety": _safety_boundary(),
        }
    report = build_paper_pipeline_report(
        selected_symbol=selected_symbol,
        anomaly_symbols=anomaly,
        market_bundle=market_bundle,
        events=events,
        mode=args.mode,
        requested_notional_usdt=getattr(args, "notional_usdt", None),
        requested_margin_usdt=getattr(args, "agent_margin_usdt", None),
        paper_leverage=getattr(args, "paper_leverage", None),
        margin_budget_usdt=getattr(args, "paper_margin_budget_usdt", None),
        sizing_source=_sizing_source_from_args(args),
        agent_trade_thesis=agent_trade_thesis,
        paper_autonomy_profile=paper_autonomy_profile,
        risk_policy=_risk_policy_from_args(args),
        paper_fee_bps=_non_negative_arg(args, "paper_fee_bps", BINANCE_USDM_PUBLIC_TAKER_FEE_BPS),
        paper_slippage_bps=_non_negative_arg(args, "paper_slippage_bps", DEFAULT_PAPER_SLIPPAGE_BPS),
    )
    report["universe"] = _summarize_universe(universe)
    report["signal_flow_events"] = {
        "ok": signal_flow.get("ok"),
        "count": len(signal_flow.get("events") or []),
        "rejected_count": len(signal_flow.get("rejected") or []),
        "duplicate_count": signal_flow.get("duplicate_count") or len(signal_flow.get("duplicates") or []),
    }
    report["anomaly_symbols"] = {
        "ok": anomaly.get("ok"),
        "count": len(anomaly.get("symbols") or []),
        "row_count": len(anomaly.get("rows") or anomaly.get("symbols") or []),
        "sections": anomaly.get("sections") or [],
        "first_10_rows": (anomaly.get("rows") or anomaly.get("symbols") or [])[:10],
        "rejected_count": len(anomaly.get("rejected") or []),
    }
    report["raw_errors"] = _collect_errors(universe, signal_flow, events, anomaly, market_bundle)
    return report


def run_loop_public(
    args: argparse.Namespace,
    *,
    client: Any | None = None,
    source: Any | None = None,
    sleep_func: Any | None = None,
) -> dict[str, Any]:
    _validate_paper_cost_inputs(args)
    if str(getattr(args, "agent_trade_thesis_path", "") or "").strip():
        try:
            _agent_trade_thesis_from_args(args)
        except ValueError as exc:
            return _agent_trade_thesis_load_failed_payload(args, "tradecat_auto.cli.run_loop_public", exc)
    if str(getattr(args, "paper_autonomy_profile_path", "") or "").strip():
        try:
            _paper_autonomy_profile_from_args(args)
        except ValueError as exc:
            return _paper_autonomy_profile_load_failed_payload(args, "tradecat_auto.cli.run_loop_public", exc)
    market_client = client or BinanceMarketClient(base_url=args.base_url)
    tradecat_source = source or TradeCatPublicSource(Path(args.tradecat_public))
    sleeper = sleep_func or time.sleep
    state_path = Path(getattr(args, "state_path", DEFAULT_STATE_PATH))
    max_cycles = int(getattr(args, "max_cycles", 0) or 0)
    run_once = bool(getattr(args, "once", False))
    interval_seconds = float(getattr(args, "interval_seconds", 60.0))
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be positive")
    if max_cycles < 0:
        raise ValueError("max_cycles must be non-negative")
    cycles = 0
    last_report: dict[str, Any] = {}
    while True:
        last_report = run_service_cycle(args, state_path=state_path, client=market_client, source=tradecat_source)
        cycles += 1
        if run_once or (max_cycles and cycles >= max_cycles):
            return last_report
        sleeper(interval_seconds)


def paper_report(args: argparse.Namespace) -> dict[str, Any]:
    initial_balance = _non_negative_arg(args, "initial_balance_usdt", 1000.0)
    detail_limit = _paper_report_detail_limit(args)
    ledger_path = Path(args.ledger_path)
    try:
        ledger = load_paper_ledger(ledger_path, initial_balance_usdt=initial_balance)
    except (PaperLedgerError, OSError) as exc:
        return {
            "schema": "tradecat_auto.paper_report.v1",
            "schema_version": "1.0.0",
            "ok": False,
            **paper_watch_report_flags(),
            "ledger_path": str(ledger_path),
            "error_code": "paper_ledger_load_failed",
            "error": _format_exception(exc),
            "provenance": _paper_report_provenance(ledger_path),
            "safety": _safety_boundary(),
        }
    return {
        "schema": "tradecat_auto.paper_report.v1",
        "schema_version": "1.0.0",
        "ok": True,
        **paper_watch_report_flags(),
        "error_code": None,
        "ledger_path": str(ledger_path),
        "provenance": _paper_report_provenance(ledger_path),
        "safety": _safety_boundary(),
        "detail_limit": detail_limit,
        "detail_truncated": _paper_report_detail_truncated(ledger, detail_limit),
        "summary": paper_ledger_summary(ledger),
        "paper_account_state": paper_account_state(ledger, open_positions_limit=_limit_or_none(detail_limit)),
        "open_positions": _tail_mapping(ledger.get("open_positions"), detail_limit),
        "closed_positions": _tail_list(ledger.get("closed_positions"), detail_limit),
        "recent_paper_orders": _tail_list(ledger.get("paper_orders"), detail_limit),
        "recent_fills": _tail_list(ledger.get("fills"), detail_limit),
        "equity_curve_tail": _tail_list(ledger.get("equity_curve"), detail_limit),
    }


def strategy_review_report(args: argparse.Namespace) -> dict[str, Any]:
    try:
        report = build_strategy_review_report(
            ledger_path=Path(args.ledger_path),
            archive_path=Path(args.archive_path) if str(getattr(args, "archive_path", "") or "").strip() else None,
            min_closed_positions=int(args.min_closed_positions),
            min_symbol_trades=int(args.min_symbol_trades),
            symbol_loss_usdt=float(args.symbol_loss_usdt),
            symbol_win_rate_below=float(args.symbol_win_rate_below),
            min_signal_type_trades=int(args.min_signal_type_trades),
            signal_type_loss_usdt=float(args.signal_type_loss_usdt),
            signal_type_win_rate_below=float(args.signal_type_win_rate_below),
            min_side_trades=int(args.min_side_trades),
            side_loss_usdt=float(args.side_loss_usdt),
            side_win_rate_below=float(args.side_win_rate_below),
            max_open_positions=int(args.max_open_positions),
            max_positions_per_symbol=int(args.max_positions_per_symbol),
        )
    except ValueError as exc:
        report = {
            "schema": "tradecat_auto.strategy_review_report.v1",
            "schema_version": "1.0.0",
            "ok": False,
            "error_code": "strategy_review_invalid_input",
            "error": {
                "code": "strategy_review_invalid_input",
                "kind": "operator_input",
                "message": _format_exception(exc),
                "retryable": False,
            },
            "provenance": {"source": "tradecat_auto.cli.strategy_review_report"},
            "safety": _safety_boundary(),
        }
    output = str(getattr(args, "output_state_path", "") or "").strip()
    if output and isinstance(report.get("strategy_state"), dict):
        try:
            save_strategy_state(Path(output), report["strategy_state"])
        except OSError as exc:
            report["ok"] = False
            report["error_code"] = "strategy_state_write_failed"
            report["error"] = {
                "code": "strategy_state_write_failed",
                "kind": "local_runtime_io",
                "message": _format_exception(exc),
                "retryable": False,
            }
        else:
            report["output_state_path"] = output
    return report


def position_manage_report(args: argparse.Namespace) -> dict[str, Any]:
    ledger_path = Path(args.ledger_path)
    thesis_path = Path(args.thesis_path)
    try:
        thesis = json.loads(thesis_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _position_management_error_payload(
            code="position_management_thesis_load_failed",
            message=str(exc),
            ledger_path=ledger_path,
            thesis_path=thesis_path,
        )
    try:
        with paper_ledger_lock(ledger_path):
            ledger = load_paper_ledger(
                ledger_path, initial_balance_usdt=_non_negative_arg(args, "initial_balance_usdt", 1000.0)
            )
            result = apply_position_management_thesis(
                ledger,
                thesis if isinstance(thesis, dict) else {},
                fee_bps=_non_negative_arg(args, "paper_fee_bps", BINANCE_USDM_PUBLIC_TAKER_FEE_BPS),
                slippage_bps=_non_negative_arg(args, "paper_slippage_bps", DEFAULT_PAPER_SLIPPAGE_BPS),
                now_iso=str(getattr(args, "now", "") or "") or None,
            )
            updated_ledger = result.pop("_ledger")
            if result.get("ledger_mutated"):
                save_paper_ledger(ledger_path, updated_ledger)
    except (PaperLedgerError, OSError) as exc:
        return _position_management_error_payload(
            code="paper_ledger_load_failed",
            message=_format_exception(exc),
            ledger_path=ledger_path,
            thesis_path=thesis_path,
        )
    result["ledger_path"] = str(ledger_path)
    result["thesis_path"] = str(thesis_path)
    result["paper_ledger_summary"] = paper_ledger_summary(updated_ledger)
    journal_path = str(getattr(args, "journal_path", "") or "").strip()
    if journal_path:
        result["audit_journal"] = append_audit_record(
            Path(journal_path),
            event_type="position_management_action",
            payload=result,
            run_id=str(result.get("provenance", {}).get("research_cycle_run_id") or result.get("action_id") or ""),
            idempotency_key=f"position_management_action:{result.get('action_id')}",
            created_at=str(getattr(args, "now", "") or "") or None,
        )
    return result


def soft_layer_report(args: argparse.Namespace) -> dict[str, Any]:
    return build_agent_soft_layer_bundle(include_prompt_text=not bool(getattr(args, "no_prompt_text", False)))


def research_cycle_report(args: argparse.Namespace, *, source: Any | None = None) -> dict[str, Any]:
    tradecat_source = source or TradeCatPublicSource(Path(args.tradecat_public))
    anomaly = _safe_call(
        tradecat_source.fetch_anomaly_symbols,
        tradable_symbols=set(),
        limit=getattr(args, "anomaly_limit", 20),
    )
    signal_flow = _fetch_signal_flow_events(tradecat_source, set(), limit=getattr(args, "event_limit", 20))
    selected_symbol = _select_symbol(str(getattr(args, "symbol", "auto") or "auto"), set(), anomaly, signal_flow)
    events = signal_events_payload(signal_flow, anomaly, selected_symbol=selected_symbol)
    payload = build_observe_only_research_cycle(
        events=events,
        anomaly_symbols=anomaly,
        requested_symbol=str(getattr(args, "symbol", "auto") or "auto"),
    )
    payload["input_status"] = {
        "events_ok": bool(events.get("ok")),
        "events_count": len(events.get("events") or []),
        "signal_flow_ok": bool(signal_flow.get("ok")),
        "signal_flow_count": len(signal_flow.get("events") or []),
        "signal_flow_duplicate_count": signal_flow.get("duplicate_count") or len(signal_flow.get("duplicates") or []),
        "anomaly_symbols_ok": bool(anomaly.get("ok")),
        "anomaly_symbols_count": len(anomaly.get("symbols") or []),
        "anomaly_rows_count": len(anomaly.get("rows") or anomaly.get("symbols") or []),
        "anomaly_sections": anomaly.get("sections") or [],
        "anomaly_rejected_count": len(anomaly.get("rejected") or []),
    }
    payload["agent_research_cycle_audit"] = audit_agent_research_cycle(payload)
    drafts = build_observe_only_drafts(payload)
    payload["agent_market_context_audit"] = drafts["agent_market_context_audit"]
    payload["observe_only_draft_schemas"] = {
        "agent_market_context": drafts["agent_market_context"]["schema"],
        "agent_trade_thesis": drafts["agent_trade_thesis"]["schema"],
    }
    output_dir = str(getattr(args, "output_dir", "") or "").strip()
    if output_dir:
        try:
            payload["draft_outputs"] = write_observe_only_drafts(payload, output_dir)
        except (OSError, ValueError) as exc:
            payload["ok"] = False
            payload["error_code"] = "observe_only_draft_write_failed"
            payload["error"] = {
                "code": "observe_only_draft_write_failed",
                "kind": "local_io",
                "message": str(exc),
                "retryable": False,
            }
    return payload


def context_audit_report(args: argparse.Namespace) -> dict[str, Any]:
    context = load_agent_market_context(Path(args.input))
    if context.get("ok") is False and context.get("error"):
        return {
            "schema": "tradecat_auto.agent_market_context_audit.v1",
            "schema_version": "1.0.0",
            "ok": False,
            "symbol": "",
            "mode": "public_readonly",
            "accepted_families": [],
            "rejected_families": [],
            "accepted_endpoints": [],
            "errors": [context["error"]],
            "warnings": [],
            "provenance": {},
            "source_manifest": DEFAULT_SOURCE_MANIFEST,
            "safety_boundary_enforced": True,
            **paper_watch_report_flags(),
            "allowed_modes": sorted(ALLOWED_MODES),
            "allowed_market_context_families": sorted(ALLOWED_ENDPOINTS_BY_FAMILY),
        }
    return audit_agent_market_context(context)


def run_context_public(args: argparse.Namespace) -> dict[str, Any]:
    try:
        _validate_paper_cost_inputs(args)
    except ValueError as exc:
        return _run_context_input_error(args, "run_context_invalid_numeric_input", exc)
    context = load_agent_market_context(Path(args.input))
    if context.get("ok") is False and context.get("error"):
        return {
            "schema": "tradecat_auto.run_once_report.v1",
            "schema_version": "1.0.0",
            "ok": False,
            **paper_watch_report_flags(),
            "mode": args.mode,
            "selected_symbol": "",
            "error_code": "agent_market_context_load_failed",
            "error": "agent_market_context_load_failed",
            "agent_market_context_audit": context_audit_report(args),
            "provenance": {"source_manifest": DEFAULT_SOURCE_MANIFEST},
            "safety": _safety_boundary(),
            "limitations": ["no Binance credentials were read", "no real order was placed"],
        }
    report = build_paper_report_from_agent_market_context(
        context,
        mode=args.mode,
        requested_notional_usdt=getattr(args, "notional_usdt", None),
        requested_margin_usdt=getattr(args, "agent_margin_usdt", None),
        paper_leverage=getattr(args, "paper_leverage", None),
        margin_budget_usdt=getattr(args, "paper_margin_budget_usdt", None),
        risk_policy=_risk_policy_from_args(args),
        paper_fee_bps=_non_negative_arg(args, "paper_fee_bps", BINANCE_USDM_PUBLIC_TAKER_FEE_BPS),
        paper_slippage_bps=_non_negative_arg(args, "paper_slippage_bps", DEFAULT_PAPER_SLIPPAGE_BPS),
    )
    return _apply_run_context_runtime_writes(args, context, report)


def _run_context_input_error(args: argparse.Namespace, code: str, exc: Exception) -> dict[str, Any]:
    return {
        "schema": "tradecat_auto.run_once_report.v1",
        "schema_version": "1.0.0",
        "ok": False,
        "error_code": code,
        "mode": str(getattr(args, "mode", "paper") or "paper"),
        "selected_symbol": "",
        "error": {
            "code": code,
            "kind": "operator_input",
            "message": _format_exception(exc),
            "retryable": False,
        },
        "provenance": {
            "source": "tradecat_auto.cli.run_context_public",
            "agent_market_context_input": str(getattr(args, "input", "") or ""),
        },
        "safety": _safety_boundary(),
        "limitations": ["no Binance credentials were read", "no real order was placed"],
    }


def _apply_run_context_runtime_writes(
    args: argparse.Namespace, context: dict[str, Any], report: dict[str, Any]
) -> dict[str, Any]:
    result = dict(report)
    ledger_path_text = str(getattr(args, "ledger_path", "") or "").strip()
    archive_path_text = str(getattr(args, "archive_path", "") or "").strip()
    journal_path_text = str(getattr(args, "journal_path", "") or "").strip()
    now_iso = str(getattr(args, "now", "") or "").strip() or None
    runtime_write = {
        "schema": "tradecat_auto.run_context_runtime_write.v1",
        "schema_version": "1.0.0",
        "ok": True,
        "mode": str(getattr(args, "mode", "paper") or "paper"),
        "ledger_path": ledger_path_text,
        "archive_path": archive_path_text,
        "journal_path": journal_path_text,
        "ledger_written": False,
        "archive_written": False,
        "journal_written": False,
        "provenance": {"source": "tradecat_auto.cli.run_context_public"},
        "safety": _safety_boundary(),
    }
    result["paper_runtime_write"] = runtime_write

    if runtime_write["mode"] == "paper" and ledger_path_text and isinstance(result.get("paper_execution"), dict):
        ledger_path = Path(ledger_path_text)
        try:
            with paper_ledger_lock(ledger_path):
                ledger = load_paper_ledger(
                    ledger_path,
                    initial_balance_usdt=_non_negative_arg(args, "initial_balance_usdt", 1000.0),
                )
                ledger = apply_paper_execution(
                    ledger,
                    result["paper_execution"],
                    fee_bps=_non_negative_arg(args, "paper_fee_bps", BINANCE_USDM_PUBLIC_TAKER_FEE_BPS),
                    slippage_bps=_non_negative_arg(args, "paper_slippage_bps", DEFAULT_PAPER_SLIPPAGE_BPS),
                    now_iso=now_iso,
                )
                save_paper_ledger(ledger_path, ledger)
        except (PaperLedgerError, OSError, ValueError) as exc:
            return _run_context_runtime_write_error(result, runtime_write, "paper_ledger_write_failed", exc)
        result["paper_ledger"] = {**paper_ledger_summary(ledger), "path": str(ledger_path)}
        runtime_write["ledger_written"] = True

    cycle = _run_context_cycle_payload(args, context, result, runtime_write)
    if journal_path_text:
        try:
            result["audit_journal"] = record_service_cycle(
                Path(journal_path_text),
                cycle,
                run_id=_run_context_run_id(context, result),
                config_snapshot=_run_context_config_snapshot(args),
                created_at=now_iso,
            )
            runtime_write["journal_written"] = bool(result["audit_journal"].get("ok"))
        except (OSError, ValueError) as exc:
            return _run_context_runtime_write_error(result, runtime_write, "audit_journal_write_failed", exc)
    if archive_path_text:
        try:
            _append_jsonl(Path(archive_path_text), cycle)
        except OSError as exc:
            return _run_context_runtime_write_error(result, runtime_write, "cycle_archive_write_failed", exc)
        runtime_write["archive_written"] = True
    return result


def _run_context_runtime_write_error(
    report: dict[str, Any], runtime_write: dict[str, Any], code: str, exc: Exception
) -> dict[str, Any]:
    runtime_write["ok"] = False
    runtime_write["error_code"] = code
    runtime_write["error"] = {
        "code": code,
        "kind": "local_runtime_io",
        "message": _format_exception(exc),
        "retryable": False,
    }
    return {
        **report,
        "ok": False,
        "error_code": code,
        "error": runtime_write["error"],
        "paper_runtime_write": runtime_write,
    }


def _run_context_cycle_payload(
    args: argparse.Namespace, context: dict[str, Any], report: dict[str, Any], runtime_write: dict[str, Any]
) -> dict[str, Any]:
    event = context.get("source_event") if isinstance(context.get("source_event"), dict) else {}
    action = "RUN_CONTEXT_PAPER" if str(getattr(args, "mode", "paper") or "paper") == "paper" else "RUN_CONTEXT_WATCH"
    reason = (
        "agent_market_context_processed" if report.get("ok") else str(report.get("error_code") or "run_context_failed")
    )
    return {
        "schema": "tradecat_auto.service_cycle.v1",
        "schema_version": "1.0.0",
        "ok": bool(report.get("ok")),
        "action": action,
        "reason": reason,
        "error_code": report.get("error_code"),
        **paper_watch_report_flags(),
        "latest_event": event,
        "pipeline_report": report,
        "paper_ledger": report.get("paper_ledger") if isinstance(report.get("paper_ledger"), dict) else {},
        "paper_runtime_write": runtime_write,
        "provenance": {
            "source": "tradecat_auto.cli.run_context_public",
            "agent_market_context_input": str(getattr(args, "input", "") or ""),
        },
        "safety": _safety_boundary(),
    }


def _run_context_config_snapshot(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "schema": "tradecat_auto.run_context_config_snapshot.v1",
        "schema_version": "1.0.0",
        "command": "run-context",
        "input": str(getattr(args, "input", "") or ""),
        "mode": str(getattr(args, "mode", "paper") or "paper"),
        "ledger_path": str(getattr(args, "ledger_path", "") or ""),
        "archive_path": str(getattr(args, "archive_path", "") or ""),
        "journal_path": str(getattr(args, "journal_path", "") or ""),
        "paper_fee_bps": _non_negative_arg(args, "paper_fee_bps", BINANCE_USDM_PUBLIC_TAKER_FEE_BPS),
        "paper_slippage_bps": _non_negative_arg(args, "paper_slippage_bps", DEFAULT_PAPER_SLIPPAGE_BPS),
        **paper_watch_report_flags(),
        "safety": _safety_boundary(),
    }


def _run_context_run_id(context: dict[str, Any], report: dict[str, Any]) -> str:
    provenance = context.get("provenance") if isinstance(context.get("provenance"), dict) else {}
    event = context.get("source_event") if isinstance(context.get("source_event"), dict) else {}
    execution = report.get("paper_execution") if isinstance(report.get("paper_execution"), dict) else {}
    for source in (provenance, event, execution, report):
        for key in ("research_cycle_run_id", "run_id", "event_id", "paper_execution_id", "selected_symbol"):
            value = str(source.get(key) or "").strip()
            if value:
                return f"run-context:{value}"
    return "run-context"


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
    with paper_ledger_lock(path):
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)


def replay_report(args: argparse.Namespace) -> dict[str, Any]:
    journal_path = str(getattr(args, "journal_path", "") or "").strip()
    return build_replay_report(
        archive_path=Path(args.archive_path),
        ledger_path=Path(args.ledger_path),
        journal_path=Path(journal_path) if journal_path else None,
        generated_at=str(getattr(args, "generated_at", "") or "") or None,
    )


def audit_journal_report(args: argparse.Namespace) -> dict[str, Any]:
    return journal_summary(Path(args.journal_path))


def latest_cycle_report(args: argparse.Namespace) -> dict[str, Any]:
    return build_latest_cycle_report(archive_path=Path(args.archive_path))


def latest_decision_report(args: argparse.Namespace) -> dict[str, Any]:
    return build_latest_decision_report(archive_path=Path(args.archive_path))


def health_report(args: argparse.Namespace) -> dict[str, Any]:
    return build_health_report(
        state_path=Path(args.state_path),
        ledger_path=Path(args.ledger_path),
        archive_path=Path(args.archive_path),
        journal_path=Path(args.journal_path),
        now_iso=str(getattr(args, "now", "") or "") or None,
        max_heartbeat_age_seconds=float(getattr(args, "max_heartbeat_age_seconds", 180.0)),
    )


def daily_report(args: argparse.Namespace) -> dict[str, Any]:
    return build_daily_report(
        ledger_path=Path(args.ledger_path),
        archive_path=Path(args.archive_path),
        date=str(getattr(args, "date", "") or "") or None,
    )


def alert_payload_report(args: argparse.Namespace) -> dict[str, Any]:
    if getattr(args, "kind", "health") == "daily":
        report = daily_report(args)
    else:
        report = health_report(args)
    return build_telegram_alerts(report)


def _safe_call(func, *args, **kwargs) -> dict[str, Any]:
    try:
        result = func(*args, **kwargs)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return result if isinstance(result, dict) else {"ok": False, "error": "non-object result"}


def _format_exception(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"


def _parse_symbols_arg(value: Any) -> list[str]:
    if isinstance(value, str):
        raw_items = value.replace(",", " ").split()
    else:
        raw_items = list(value or [])
    return list(dict.fromkeys(str(item or "").upper().strip() for item in raw_items if str(item or "").strip()))


def _position_management_error_payload(
    *, code: str, message: str, ledger_path: Path, thesis_path: Path
) -> dict[str, Any]:
    return {
        "schema": "tradecat_auto.position_management_action_report.v1",
        "schema_version": "1.0.0",
        "ok": False,
        "mode": "paper",
        "action": "hold",
        "status": "ERROR",
        "error_code": code,
        "reason": message,
        "symbol": "",
        "position_id": "",
        "position_ref": {},
        "ledger_mutated": False,
        "action_id": "",
        "updated_fields": [],
        "ledger_path": str(ledger_path),
        "thesis_path": str(thesis_path),
        "provenance": {"source": "tradecat_auto.cli.position_manage_report"},
        "safety": _safety_boundary(),
    }


def _agent_trade_thesis_from_args(args: argparse.Namespace) -> dict[str, Any] | None:
    return load_agent_trade_thesis(
        getattr(args, "agent_trade_thesis_path", "") or "",
        mode=str(getattr(args, "mode", "paper") or "paper"),
    )


def _paper_autonomy_profile_from_args(args: argparse.Namespace) -> dict[str, Any] | None:
    return load_paper_autonomy_profile(
        getattr(args, "paper_autonomy_profile_path", "") or "",
        mode=str(getattr(args, "mode", "paper") or "paper"),
    )


def _risk_policy_from_args(args: argparse.Namespace) -> dict[str, Any]:
    policy: dict[str, Any] = {}
    kill_switch_path = str(getattr(args, "paper_kill_switch_path", "") or "").strip()
    if kill_switch_path:
        policy["kill_switch_file"] = kill_switch_path
    policy_path = str(getattr(args, "portfolio_risk_policy_path", "") or "").strip()
    if not policy_path:
        return policy
    try:
        loaded = load_portfolio_risk_policy(policy_path)
    except ValueError as exc:
        policy.setdefault("force_reject_reasons", []).append("portfolio_risk_policy_load_failed")
        policy["portfolio_risk_policy_error"] = str(exc)
        return policy
    if loaded is not None:
        policy["portfolio_risk_policy"] = loaded
    return policy


def _agent_trade_thesis_load_failed_payload(args: argparse.Namespace, source: str, exc: Exception) -> dict[str, Any]:
    command = str(getattr(args, "command", "") or "")
    schema = "tradecat_auto.service_cycle.v1" if command == "run-loop" else "tradecat_auto.run_once_report.v1"
    payload: dict[str, Any] = {
        "schema": schema,
        "schema_version": "1.0.0",
        "ok": False,
        **paper_watch_report_flags(),
        "mode": str(getattr(args, "mode", "paper") or "paper"),
        "selected_symbol": "",
        "error_code": "agent_trade_thesis_load_failed",
        "error": {
            "code": "agent_trade_thesis_load_failed",
            "kind": "input_validation",
            "message": str(exc),
            "retryable": False,
        },
        "provenance": {
            "source": source,
            "agent_trade_thesis_path": str(getattr(args, "agent_trade_thesis_path", "") or ""),
        },
        "safety": _safety_boundary(),
    }
    if command == "run-loop":
        payload.update({"action": "ERROR", "reason": "agent_trade_thesis_load_failed"})
    return payload


def _paper_autonomy_profile_load_failed_payload(
    args: argparse.Namespace, source: str, exc: Exception
) -> dict[str, Any]:
    command = str(getattr(args, "command", "") or "")
    schema = "tradecat_auto.service_cycle.v1" if command == "run-loop" else "tradecat_auto.run_once_report.v1"
    payload: dict[str, Any] = {
        "schema": schema,
        "schema_version": "1.0.0",
        "ok": False,
        **paper_watch_report_flags(),
        "mode": str(getattr(args, "mode", "paper") or "paper"),
        "selected_symbol": "",
        "error_code": "paper_autonomy_profile_load_failed",
        "error": {
            "code": "paper_autonomy_profile_load_failed",
            "kind": "input_validation",
            "message": str(exc),
            "retryable": False,
        },
        "provenance": {
            "source": source,
            "paper_autonomy_profile_path": str(getattr(args, "paper_autonomy_profile_path", "") or ""),
        },
        "safety": _safety_boundary(),
    }
    if command == "run-loop":
        payload.update({"action": "ERROR", "reason": "paper_autonomy_profile_load_failed"})
    return payload


def _validate_paper_cost_inputs(args: argparse.Namespace) -> None:
    _non_negative_arg(args, "initial_balance_usdt", 1000.0)
    _non_negative_arg(args, "paper_fee_bps", BINANCE_USDM_PUBLIC_TAKER_FEE_BPS)
    _non_negative_arg(args, "paper_slippage_bps", DEFAULT_PAPER_SLIPPAGE_BPS)
    _positive_optional_arg(args, "paper_leverage")
    _positive_optional_arg(args, "agent_margin_usdt")
    _positive_optional_arg(args, "notional_usdt")
    _positive_optional_arg(args, "paper_margin_budget_usdt")


def _sizing_source_from_args(args: argparse.Namespace) -> str:
    if getattr(args, "agent_margin_usdt", None) is not None:
        return "agent_supplied_cli_margin"
    if getattr(args, "notional_usdt", None) is not None:
        return "explicit_cli_effective_notional"
    if getattr(args, "paper_leverage", None) is not None:
        return "incomplete_cli_sizing"
    return "agent_required_missing"


def _positive_optional_arg(args: argparse.Namespace, name: str) -> float | None:
    value = getattr(args, name, None)
    if value is None or value == "":
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive number") from exc
    if numeric <= 0:
        raise ValueError(f"{name} must be positive")
    return numeric


def _positive_arg(args: argparse.Namespace, name: str, default: float) -> float:
    value = getattr(args, name, default)
    try:
        numeric = float(default if value is None else value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive number") from exc
    if numeric <= 0:
        raise ValueError(f"{name} must be positive")
    return numeric


def _non_negative_arg(args: argparse.Namespace, name: str, default: float) -> float:
    value = getattr(args, name, default)
    try:
        numeric = float(default if value is None else value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a non-negative number") from exc
    if numeric < 0:
        raise ValueError(f"{name} must be non-negative")
    return numeric


def _fetch_signal_flow_events(source: Any, tradable: set[str], *, limit: int) -> dict[str, Any]:
    fetch = getattr(source, "fetch_signal_flow_events", None)
    if not callable(fetch):
        return {
            "schema": "tradecat_auto.signal_flow_events.v1",
            "schema_version": "1.0.0",
            "ok": False,
            "source_dataset_key": "signal_flow",
            "events": [],
            "rejected": [],
            "error_code": "signal_flow_source_not_available",
            "error": {"code": "signal_flow_source_not_available", "message": "source has no fetch_signal_flow_events"},
        }
    return _safe_call(fetch, tradable_symbols=tradable, limit=limit)


def _select_symbol(
    requested: str, tradable: set[str], anomaly: dict[str, Any], signal_flow: dict[str, Any] | None = None
) -> str:
    text = str(requested or "auto").upper().strip()
    if text and text != "AUTO":
        return normalize_to_usdt_perp_symbol(text, tradable) or text
    for item in (signal_flow or {}).get("events") or []:
        if isinstance(item, dict) and item.get("symbol"):
            return str(item["symbol"]).upper().strip()
    for item in anomaly.get("symbols") or []:
        if isinstance(item, dict) and item.get("normalized_symbol"):
            return str(item["normalized_symbol"])
    return ""


def _summarize_universe(universe: dict[str, Any]) -> dict[str, Any]:
    symbols = universe.get("symbols") or []
    return {
        "ok": universe.get("ok"),
        "symbol_count": len(symbols),
        "first_10": symbols[:10],
        "rate_limits": universe.get("rate_limits", [])[:3],
        "error": universe.get("error"),
    }


def _summarize_market_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": bundle.get("ok"),
        "symbol": bundle.get("symbol"),
        "ticker24hr": _pick(
            bundle.get("ticker24hr"), ["symbol", "lastPrice", "priceChangePercent", "volume", "quoteVolume"]
        ),
        "bookTicker": _pick(bundle.get("bookTicker"), ["bidPrice", "bidQty", "askPrice", "askQty", "time"]),
        "depth_summary": bundle.get("depth_summary"),
        "openInterest": _pick(bundle.get("openInterest"), ["openInterest", "time"]),
        "openInterestHist_latest": _first(bundle.get("openInterestHist")),
        "fundingRate_latest": _first(bundle.get("fundingRate")),
        "premiumIndex": _pick(
            bundle.get("premiumIndex"), ["markPrice", "indexPrice", "lastFundingRate", "nextFundingTime", "time"]
        ),
        "topLongShortAccountRatio_latest": _first(bundle.get("topLongShortAccountRatio")),
        "topLongShortPositionRatio_latest": _first(bundle.get("topLongShortPositionRatio")),
        "globalLongShortAccountRatio_latest": _first(bundle.get("globalLongShortAccountRatio")),
        "takerlongshortRatio_latest": _first(bundle.get("takerlongshortRatio")),
        "errors": bundle.get("errors", {}),
    }


def _first(value: Any) -> Any:
    if isinstance(value, list) and value:
        return value[0]
    return None


def _pick(value: Any, keys: list[str]) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {key: value.get(key) for key in keys if key in value}


def _collect_errors(*payloads: dict[str, Any]) -> list[Any]:
    errors: list[Any] = []
    for payload in payloads:
        if payload.get("ok") is False:
            errors.append(payload.get("error") or payload.get("errors") or payload)
    return errors


def _print(payload: dict[str, Any], *, as_json: bool) -> None:
    try:
        if as_json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(payload, ensure_ascii=False))
    except BrokenPipeError:
        return


def _paper_report_provenance(ledger_path: Path) -> dict[str, Any]:
    return {
        "source": "local_tradecat_paper_ledger",
        "ledger_path": str(ledger_path),
    }


def _paper_report_detail_limit(args: argparse.Namespace) -> int:
    try:
        return max(0, int(getattr(args, "detail_limit", 20) or 0))
    except (TypeError, ValueError):
        return 20


def _limit_or_none(limit: int) -> int | None:
    return limit if limit > 0 else None


def _tail_list(value: Any, limit: int) -> list[Any]:
    items = list(value or []) if isinstance(value, list) else []
    return items if limit <= 0 else items[-limit:]


def _tail_mapping(value: Any, limit: int) -> dict[str, Any]:
    items = list((value or {}).items()) if isinstance(value, dict) else []
    if limit > 0:
        items = items[-limit:]
    return dict(items)


def _paper_report_detail_truncated(ledger: dict[str, Any], limit: int) -> dict[str, bool]:
    if limit <= 0:
        return {
            "open_positions": False,
            "closed_positions": False,
            "paper_orders": False,
            "fills": False,
            "equity_curve": False,
        }
    return {
        "open_positions": len(ledger.get("open_positions") or {}) > limit,
        "closed_positions": len(ledger.get("closed_positions") or []) > limit,
        "paper_orders": len(ledger.get("paper_orders") or []) > limit,
        "fills": len(ledger.get("fills") or []) > limit,
        "equity_curve": len(ledger.get("equity_curve") or []) > limit,
    }


def _safety_boundary() -> dict[str, bool]:
    return paper_watch_safety_boundary()


if __name__ == "__main__":
    raise SystemExit(main())
