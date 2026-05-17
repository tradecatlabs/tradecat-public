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
    build_paper_report_from_agent_market_context,
    load_agent_market_context,
)
from tradecat_auto.agent_soft_layer import build_agent_soft_layer_bundle
from tradecat_auto.audit_journal import journal_summary
from tradecat_auto.binance_market import BinanceMarketClient, normalize_to_usdt_perp_symbol
from tradecat_auto.paper_ledger import PaperLedgerError, load_paper_ledger, paper_account_state, paper_ledger_summary
from tradecat_auto.pipeline import build_paper_pipeline_report
from tradecat_auto.production_control import build_daily_report, build_health_report, build_telegram_alerts
from tradecat_auto.replay import build_replay_report
from tradecat_auto.service import DEFAULT_STATE_PATH, run_service_cycle
from tradecat_auto.tradecat_source import DEFAULT_TRADECAT_PUBLIC, TradeCatPublicSource


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TradeCat Auto public/read-only probes")
    sub = parser.add_subparsers(dest="command", required=True)

    universe = sub.add_parser("market-universe", help="Fetch Binance USDⓈ-M USDT perpetual universe")
    universe.add_argument("--base-url", default="https://fapi.binance.com")
    universe.add_argument("--json", action="store_true", help="Emit JSON")

    probe = sub.add_parser("probe-public", help="Probe TradeCat public sheets and Binance public market endpoints")
    probe.add_argument("--tradecat-public", default=str(DEFAULT_TRADECAT_PUBLIC))
    probe.add_argument("--base-url", default="https://fapi.binance.com")
    probe.add_argument("--symbol", default="auto", help="Symbol to probe, or auto to use first anomaly candidate")
    probe.add_argument("--event-limit", type=int, default=5)
    probe.add_argument("--anomaly-limit", type=int, default=20)
    probe.add_argument("--json", action="store_true", help="Emit JSON")

    run_once = sub.add_parser("run-once", help="Run one public-readonly analysis cycle and paper simulation")
    run_once.add_argument("--tradecat-public", default=str(DEFAULT_TRADECAT_PUBLIC))
    run_once.add_argument("--base-url", default="https://fapi.binance.com")
    run_once.add_argument("--symbol", default="auto", help="Symbol to run, or auto to use first anomaly candidate")
    run_once.add_argument("--mode", choices=["paper", "watch", "mainnet"], default="paper")
    run_once.add_argument("--notional-usdt", type=float, default=None, help="Explicit effective paper notional; no default")
    run_once.add_argument("--agent-margin-usdt", type=float, default=None, help="Agent-decided paper margin; no default")
    run_once.add_argument("--paper-leverage", type=float, default=None, help="Agent-decided paper leverage; no default")
    run_once.add_argument("--paper-margin-budget-usdt", type=float, default=None, help="Optional paper margin cap; omitted means no cap and no default order amount")
    run_once.add_argument("--event-limit", type=int, default=5)
    run_once.add_argument("--anomaly-limit", type=int, default=20)
    run_once.add_argument("--json", action="store_true", help="Emit JSON")

    run_loop = sub.add_parser("run-loop", help="Run a safe polling loop around public-readonly paper cycles")
    run_loop.add_argument("--tradecat-public", default=str(DEFAULT_TRADECAT_PUBLIC))
    run_loop.add_argument("--base-url", default="https://fapi.binance.com")
    run_loop.add_argument("--symbol", default="auto", help="Symbol to run, or auto to use first anomaly candidate")
    run_loop.add_argument("--mode", choices=["paper", "watch"], default="paper")
    run_loop.add_argument("--notional-usdt", type=float, default=None, help="Explicit effective paper notional; no default")
    run_loop.add_argument("--agent-margin-usdt", type=float, default=None, help="Agent-decided paper margin; no default")
    run_loop.add_argument("--paper-leverage", type=float, default=None, help="Agent-decided paper leverage; no default")
    run_loop.add_argument("--paper-margin-budget-usdt", type=float, default=None, help="Optional paper margin cap; omitted means no cap and no default order amount")
    run_loop.add_argument("--event-limit", type=int, default=5)
    run_loop.add_argument("--anomaly-limit", type=int, default=20)
    run_loop.add_argument("--state-path", default=str(DEFAULT_STATE_PATH))
    run_loop.add_argument("--ledger-path", default="", help="Optional persistent paper ledger JSON path")
    run_loop.add_argument("--archive-path", default="", help="Optional JSONL path for full service-cycle replay records")
    run_loop.add_argument("--journal-path", default="", help="Optional SQLite audit journal path for run/config/decision/order/fill records")
    run_loop.add_argument("--initial-balance-usdt", type=float, default=1000.0)
    run_loop.add_argument("--paper-fee-bps", type=float, default=2.0)
    run_loop.add_argument("--paper-slippage-bps", type=float, default=0.5)
    run_loop.add_argument("--paper-max-holding-minutes", type=float, default=0.0, help="Deprecated status/config field; paper time stops require Agent/strategy max_holding_minutes")
    run_loop.add_argument("--interval-seconds", type=float, default=60.0)
    run_loop.add_argument("--max-cycles", type=int, default=0, help="Stop after N cycles; 0 means run until interrupted")
    run_loop.add_argument("--once", action="store_true", help="Run exactly one service cycle and exit")
    run_loop.add_argument("--max-event-age-seconds", type=float, default=300.0)
    run_loop.add_argument("--json", action="store_true", help="Emit JSON")

    paper = sub.add_parser("paper-report", help="Summarize the persistent paper ledger")
    paper.add_argument("--ledger-path", default=".runtime/paper_ledger.json")
    paper.add_argument("--initial-balance-usdt", type=float, default=1000.0)
    paper.add_argument("--json", action="store_true", help="Emit JSON")

    soft_layer = sub.add_parser("soft-layer", help="Show self-contained Agent soft prompt/policy bundle")
    soft_layer.add_argument("--no-prompt-text", action="store_true", help="List prompt paths without embedding template text")
    soft_layer.add_argument("--json", action="store_true", help="Emit JSON")

    context_audit = sub.add_parser("context-audit", help="Audit Agent-supplied public/read-only market context JSON")
    context_audit.add_argument("--input", required=True, help="Path to agent market context JSON")
    context_audit.add_argument("--json", action="store_true", help="Emit JSON")

    run_context = sub.add_parser("run-context", help="Run paper/watch pipeline from Agent-supplied market context JSON")
    run_context.add_argument("--input", required=True, help="Path to agent market context JSON")
    run_context.add_argument("--mode", choices=["paper", "watch", "mainnet"], default="paper")
    run_context.add_argument("--notional-usdt", type=float, default=None, help="Explicit effective paper notional override; no default")
    run_context.add_argument("--agent-margin-usdt", type=float, default=None, help="Agent-decided paper margin override; no default")
    run_context.add_argument("--paper-leverage", type=float, default=None, help="Agent-decided paper leverage override; no default")
    run_context.add_argument("--paper-margin-budget-usdt", type=float, default=None, help="Optional paper margin cap; omitted means no cap and no default order amount")
    run_context.add_argument("--json", action="store_true", help="Emit JSON")

    replay = sub.add_parser("replay-report", help="Build a reproducible replay/backtest report from service-cycle archive and paper ledger")
    replay.add_argument("--archive-path", default=".runtime/cycles.jsonl")
    replay.add_argument("--ledger-path", default=".runtime/paper_ledger.json")
    replay.add_argument("--json", action="store_true", help="Emit JSON")

    audit_journal = sub.add_parser("audit-journal", help="Summarize the local SQLite append-only audit journal")
    audit_journal.add_argument("--journal-path", default=".runtime/auto-paper/paper_audit.sqlite3")
    audit_journal.add_argument("--json", action="store_true", help="Emit JSON")

    health = sub.add_parser("health-report", help="Summarize production heartbeat, ledger, cycle archive, and audit journal")
    health.add_argument("--state-path", default=".runtime/auto-paper/service_state.json")
    health.add_argument("--ledger-path", default=".runtime/auto-paper/paper_ledger.json")
    health.add_argument("--archive-path", default=".runtime/auto-paper/cycles.jsonl")
    health.add_argument("--journal-path", default=".runtime/auto-paper/paper_audit.sqlite3")
    health.add_argument("--now", default="", help="Optional ISO timestamp for deterministic checks")
    health.add_argument("--max-heartbeat-age-seconds", type=float, default=180.0)
    health.add_argument("--json", action="store_true", help="Emit JSON")

    daily = sub.add_parser("daily-report", help="Build a daily paper production report from ledger and cycle archive")
    daily.add_argument("--ledger-path", default=".runtime/auto-paper/paper_ledger.json")
    daily.add_argument("--archive-path", default=".runtime/auto-paper/cycles.jsonl")
    daily.add_argument("--date", default="", help="Report date YYYY-MM-DD; defaults to today")
    daily.add_argument("--json", action="store_true", help="Emit JSON")

    alerts = sub.add_parser("alert-payload", help="Build Telegram-friendly alert payload from health or daily report")
    alerts.add_argument("--kind", choices=["health", "daily"], default="health")
    alerts.add_argument("--state-path", default=".runtime/auto-paper/service_state.json")
    alerts.add_argument("--ledger-path", default=".runtime/auto-paper/paper_ledger.json")
    alerts.add_argument("--archive-path", default=".runtime/auto-paper/cycles.jsonl")
    alerts.add_argument("--journal-path", default=".runtime/auto-paper/paper_audit.sqlite3")
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
    if args.command == "soft-layer":
        payload = soft_layer_report(args)
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
        return _market_universe_error_payload(args.base_url, TypeError("market_universe returned non-object result"), client)
    return payload


def _market_universe_error_payload(base_url: str, exc: Exception, client: Any) -> dict[str, Any]:
    return {
        "schema": "tradecat_auto.market_universe.v1",
        "schema_version": "1.0.0",
        "ok": False,
        "real_orders": False,
        "signed_requests": False,
        "reads_api_keys": False,
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
    events = _safe_call(source.fetch_events, limit=args.event_limit)
    anomaly = _safe_call(source.fetch_anomaly_symbols, tradable_symbols=tradable, limit=args.anomaly_limit)
    selected_symbol = _select_symbol(args.symbol, tradable, anomaly)
    market_bundle = _safe_call(client.fetch_public_market_bundle, selected_symbol) if selected_symbol else {
        "schema": "tradecat_auto.public_market_bundle.v1",
        "schema_version": "1.0.0",
        "ok": False,
        "error_code": "no_symbol_selected",
        "real_orders": False,
        "signed_requests": False,
        "reads_api_keys": False,
        "errors": {"symbol": "no tradable symbol selected"},
        "provenance": {"source": "tradecat_auto.cli.probe_public", "selected_symbol": ""},
        "safety": _safety_boundary(),
    }
    ok = bool(universe.get("ok") and events.get("ok") and anomaly.get("ok") and market_bundle.get("ok"))
    return {
        "schema": "tradecat_auto.public_probe.v1",
        "schema_version": "1.0.0",
        "ok": ok,
        "real_orders": False,
        "signed_requests": False,
        "reads_api_keys": False,
        "error_code": None if ok else "public_probe_failed",
        "mode": "public_readonly_no_credentials_no_orders",
        "tradecat_public": str(Path(args.tradecat_public)),
        "binance_base_url": args.base_url,
        "selected_symbol": selected_symbol,
        "universe": _summarize_universe(universe),
        "events": {
            "ok": events.get("ok"),
            "count": len(events.get("events") or []),
            "latest": (events.get("events") or [None])[0],
        },
        "anomaly_symbols": {
            "ok": anomaly.get("ok"),
            "count": len(anomaly.get("symbols") or []),
            "first_10": (anomaly.get("symbols") or [])[:10],
            "rejected_count": len(anomaly.get("rejected") or []),
        },
        "market_bundle": _summarize_market_bundle(market_bundle),
        "raw_errors": _collect_errors(universe, events, anomaly, market_bundle),
        "provenance": {
            "source": "tradecat_auto.cli.probe_public",
            "tradecat_public": str(Path(args.tradecat_public)),
            "binance_base_url": args.base_url,
            "selected_symbol": selected_symbol,
        },
        "safety": _safety_boundary(),
    }


def run_once_public(args: argparse.Namespace, *, client: Any | None = None, source: Any | None = None) -> dict[str, Any]:
    market_client = client or BinanceMarketClient(base_url=args.base_url)
    tradecat_source = source or TradeCatPublicSource(Path(args.tradecat_public))
    universe = _safe_call(market_client.market_universe)
    tradable = set(universe.get("symbols") or []) if universe.get("ok") else set()
    events = _safe_call(tradecat_source.fetch_events, limit=args.event_limit)
    anomaly = _safe_call(tradecat_source.fetch_anomaly_symbols, tradable_symbols=tradable, limit=args.anomaly_limit)
    selected_symbol = _select_symbol(args.symbol, tradable, anomaly)
    market_bundle = _safe_call(market_client.fetch_public_market_bundle, selected_symbol) if selected_symbol else {
        "schema": "tradecat_auto.public_market_bundle.v1",
        "schema_version": "1.0.0",
        "ok": False,
        "error_code": "no_symbol_selected",
        "real_orders": False,
        "signed_requests": False,
        "reads_api_keys": False,
        "errors": {"symbol": "no tradable symbol selected"},
        "provenance": {"source": "tradecat_auto.cli.run_once_public", "selected_symbol": ""},
        "safety": _safety_boundary(),
    }
    if not selected_symbol:
        return {
            "schema": "tradecat_auto.run_once_report.v1",
            "schema_version": "1.0.0",
            "ok": False,
            "real_orders": False,
            "signed_requests": False,
            "reads_api_keys": False,
            "mode": args.mode,
            "selected_symbol": "",
            "error_code": "no_symbol_selected",
            "error": "no_symbol_selected",
            "universe": _summarize_universe(universe),
            "raw_errors": _collect_errors(universe, events, anomaly, market_bundle),
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
    )
    report["universe"] = _summarize_universe(universe)
    report["anomaly_symbols"] = {
        "ok": anomaly.get("ok"),
        "count": len(anomaly.get("symbols") or []),
        "rejected_count": len(anomaly.get("rejected") or []),
    }
    report["raw_errors"] = _collect_errors(universe, events, anomaly, market_bundle)
    return report


def run_loop_public(
    args: argparse.Namespace,
    *,
    client: Any | None = None,
    source: Any | None = None,
    sleep_func: Any | None = None,
) -> dict[str, Any]:
    _validate_paper_cost_inputs(args)
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
    ledger_path = Path(args.ledger_path)
    try:
        ledger = load_paper_ledger(ledger_path, initial_balance_usdt=initial_balance)
    except (PaperLedgerError, OSError) as exc:
        return {
            "schema": "tradecat_auto.paper_report.v1",
            "schema_version": "1.0.0",
            "ok": False,
            "real_orders": False,
            "signed_requests": False,
            "reads_api_keys": False,
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
        "real_orders": False,
        "signed_requests": False,
        "reads_api_keys": False,
        "error_code": None,
        "ledger_path": str(ledger_path),
        "provenance": _paper_report_provenance(ledger_path),
        "safety": _safety_boundary(),
        "summary": paper_ledger_summary(ledger),
        "paper_account_state": paper_account_state(ledger),
        "open_positions": ledger.get("open_positions", {}),
        "closed_positions": ledger.get("closed_positions", [])[-20:],
        "recent_paper_orders": ledger.get("paper_orders", [])[-20:],
        "recent_fills": ledger.get("fills", [])[-20:],
        "equity_curve_tail": ledger.get("equity_curve", [])[-50:],
    }


def soft_layer_report(args: argparse.Namespace) -> dict[str, Any]:
    return build_agent_soft_layer_bundle(include_prompt_text=not bool(getattr(args, "no_prompt_text", False)))


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
            "real_orders": False,
            "signed_requests": False,
            "reads_api_keys": False,
            "allowed_modes": sorted(ALLOWED_MODES),
            "allowed_market_context_families": sorted(ALLOWED_ENDPOINTS_BY_FAMILY),
        }
    return audit_agent_market_context(context)


def run_context_public(args: argparse.Namespace) -> dict[str, Any]:
    context = load_agent_market_context(Path(args.input))
    if context.get("ok") is False and context.get("error"):
        return {
            "schema": "tradecat_auto.run_once_report.v1",
            "schema_version": "1.0.0",
            "ok": False,
            "real_orders": False,
            "signed_requests": False,
            "reads_api_keys": False,
            "mode": args.mode,
            "selected_symbol": "",
            "error_code": "agent_market_context_load_failed",
            "error": "agent_market_context_load_failed",
            "agent_market_context_audit": context_audit_report(args),
            "provenance": {"source_manifest": DEFAULT_SOURCE_MANIFEST},
            "safety": _safety_boundary(),
            "limitations": ["no Binance credentials were read", "no real order was placed"],
        }
    return build_paper_report_from_agent_market_context(
        context,
        mode=args.mode,
        requested_notional_usdt=getattr(args, "notional_usdt", None),
        requested_margin_usdt=getattr(args, "agent_margin_usdt", None),
        paper_leverage=getattr(args, "paper_leverage", None),
        margin_budget_usdt=getattr(args, "paper_margin_budget_usdt", None),
    )


def replay_report(args: argparse.Namespace) -> dict[str, Any]:
    return build_replay_report(archive_path=Path(args.archive_path), ledger_path=Path(args.ledger_path))


def audit_journal_report(args: argparse.Namespace) -> dict[str, Any]:
    return journal_summary(Path(args.journal_path))


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


def _validate_paper_cost_inputs(args: argparse.Namespace) -> None:
    _non_negative_arg(args, "initial_balance_usdt", 1000.0)
    _non_negative_arg(args, "paper_fee_bps", 2.0)
    _non_negative_arg(args, "paper_slippage_bps", 0.5)
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


def _select_symbol(requested: str, tradable: set[str], anomaly: dict[str, Any]) -> str:
    text = str(requested or "auto").upper().strip()
    if text and text != "AUTO":
        return normalize_to_usdt_perp_symbol(text, tradable) or text
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
        "ticker24hr": _pick(bundle.get("ticker24hr"), ["symbol", "lastPrice", "priceChangePercent", "volume", "quoteVolume"]),
        "bookTicker": _pick(bundle.get("bookTicker"), ["bidPrice", "bidQty", "askPrice", "askQty", "time"]),
        "depth_summary": bundle.get("depth_summary"),
        "openInterest": _pick(bundle.get("openInterest"), ["openInterest", "time"]),
        "openInterestHist_latest": _first(bundle.get("openInterestHist")),
        "fundingRate_latest": _first(bundle.get("fundingRate")),
        "premiumIndex": _pick(bundle.get("premiumIndex"), ["markPrice", "indexPrice", "lastFundingRate", "nextFundingTime", "time"]),
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
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(payload, ensure_ascii=False))


def _paper_report_provenance(ledger_path: Path) -> dict[str, Any]:
    return {
        "source": "local_tradecat_paper_ledger",
        "ledger_path": str(ledger_path),
    }


def _safety_boundary() -> dict[str, bool]:
    return {
        "public_readonly_market_data": True,
        "paper_or_watch_only": True,
        "real_orders": False,
        "signed_requests": False,
        "reads_api_keys": False,
        "binance_account_state": False,
    }


if __name__ == "__main__":
    raise SystemExit(main())
