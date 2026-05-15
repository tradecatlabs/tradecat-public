from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from tradecat_auto.agent_market_context import (
    audit_agent_market_context,
    build_paper_report_from_agent_market_context,
    load_agent_market_context,
)
from tradecat_auto.binance_market import BinanceMarketClient, normalize_to_usdt_perp_symbol
from tradecat_auto.paper_ledger import PaperLedgerError, load_paper_ledger, paper_ledger_summary
from tradecat_auto.pipeline import build_paper_pipeline_report
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
    run_once.add_argument("--notional-usdt", type=float, default=10.0)
    run_once.add_argument("--event-limit", type=int, default=5)
    run_once.add_argument("--anomaly-limit", type=int, default=20)
    run_once.add_argument("--json", action="store_true", help="Emit JSON")

    run_loop = sub.add_parser("run-loop", help="Run a safe polling loop around public-readonly paper cycles")
    run_loop.add_argument("--tradecat-public", default=str(DEFAULT_TRADECAT_PUBLIC))
    run_loop.add_argument("--base-url", default="https://fapi.binance.com")
    run_loop.add_argument("--symbol", default="auto", help="Symbol to run, or auto to use first anomaly candidate")
    run_loop.add_argument("--mode", choices=["paper", "watch"], default="paper")
    run_loop.add_argument("--notional-usdt", type=float, default=10.0)
    run_loop.add_argument("--event-limit", type=int, default=5)
    run_loop.add_argument("--anomaly-limit", type=int, default=20)
    run_loop.add_argument("--state-path", default=str(DEFAULT_STATE_PATH))
    run_loop.add_argument("--ledger-path", default="", help="Optional persistent paper ledger JSON path")
    run_loop.add_argument("--archive-path", default="", help="Optional JSONL path for full service-cycle replay records")
    run_loop.add_argument("--initial-balance-usdt", type=float, default=1000.0)
    run_loop.add_argument("--paper-fee-bps", type=float, default=4.0)
    run_loop.add_argument("--paper-slippage-bps", type=float, default=5.0)
    run_loop.add_argument("--interval-seconds", type=float, default=60.0)
    run_loop.add_argument("--max-cycles", type=int, default=0, help="Stop after N cycles; 0 means run until interrupted")
    run_loop.add_argument("--once", action="store_true", help="Run exactly one service cycle and exit")
    run_loop.add_argument("--max-event-age-seconds", type=float, default=300.0)
    run_loop.add_argument("--json", action="store_true", help="Emit JSON")

    paper = sub.add_parser("paper-report", help="Summarize the persistent paper ledger")
    paper.add_argument("--ledger-path", default=".runtime/paper_ledger.json")
    paper.add_argument("--initial-balance-usdt", type=float, default=1000.0)
    paper.add_argument("--json", action="store_true", help="Emit JSON")

    context_audit = sub.add_parser("context-audit", help="Audit Agent-supplied public/read-only market context JSON")
    context_audit.add_argument("--input", required=True, help="Path to agent market context JSON")
    context_audit.add_argument("--json", action="store_true", help="Emit JSON")

    run_context = sub.add_parser("run-context", help="Run paper/watch pipeline from Agent-supplied market context JSON")
    run_context.add_argument("--input", required=True, help="Path to agent market context JSON")
    run_context.add_argument("--mode", choices=["paper", "watch", "mainnet"], default="paper")
    run_context.add_argument("--notional-usdt", type=float, default=10.0)
    run_context.add_argument("--json", action="store_true", help="Emit JSON")

    replay = sub.add_parser("replay-report", help="Build a reproducible replay/backtest report from service-cycle archive and paper ledger")
    replay.add_argument("--archive-path", default=".runtime/cycles.jsonl")
    replay.add_argument("--ledger-path", default=".runtime/paper_ledger.json")
    replay.add_argument("--json", action="store_true", help="Emit JSON")

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
        "ok": False,
        "base_url": base_url,
        "symbol_count": 0,
        "symbols": [],
        "rate_limits": [],
        "api_usage": _safe_api_usage(client),
        "error_code": "market_universe_failed",
        "error": _format_exception(exc),
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
        "ok": False,
        "errors": {"symbol": "no tradable symbol selected"},
    }
    return {
        "schema": "tradecat_auto.public_probe.v1",
        "ok": bool(universe.get("ok") and events.get("ok") and anomaly.get("ok") and market_bundle.get("ok")),
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
        "ok": False,
        "errors": {"symbol": "no tradable symbol selected"},
    }
    if not selected_symbol:
        return {
            "schema": "tradecat_auto.run_once_report.v1",
            "ok": False,
            "mode": args.mode,
            "error": "no_symbol_selected",
            "universe": _summarize_universe(universe),
            "raw_errors": _collect_errors(universe, events, anomaly, market_bundle),
        }
    report = build_paper_pipeline_report(
        selected_symbol=selected_symbol,
        anomaly_symbols=anomaly,
        market_bundle=market_bundle,
        events=events,
        mode=args.mode,
        requested_notional_usdt=args.notional_usdt,
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
            "ledger_path": str(ledger_path),
            "error_code": "paper_ledger_load_failed",
            "error": _format_exception(exc),
        }
    return {
        "schema": "tradecat_auto.paper_report.v1",
        "schema_version": "1.0.0",
        "ok": True,
        "ledger_path": str(ledger_path),
        "summary": paper_ledger_summary(ledger),
        "open_positions": ledger.get("open_positions", {}),
        "closed_positions": ledger.get("closed_positions", [])[-20:],
        "recent_fills": ledger.get("fills", [])[-20:],
        "equity_curve_tail": ledger.get("equity_curve", [])[-50:],
    }


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
            "safety_boundary_enforced": True,
            "real_orders": False,
            "signed_requests": False,
            "reads_api_keys": False,
        }
    return audit_agent_market_context(context)


def run_context_public(args: argparse.Namespace) -> dict[str, Any]:
    context = load_agent_market_context(Path(args.input))
    if context.get("ok") is False and context.get("error"):
        return {
            "schema": "tradecat_auto.run_once_report.v1",
            "schema_version": "1.0.0",
            "ok": False,
            "mode": args.mode,
            "selected_symbol": "",
            "error": "agent_market_context_load_failed",
            "agent_market_context_audit": context_audit_report(args),
            "limitations": ["no Binance credentials were read", "no real order was placed"],
        }
    return build_paper_report_from_agent_market_context(
        context,
        mode=args.mode,
        requested_notional_usdt=float(args.notional_usdt),
    )


def replay_report(args: argparse.Namespace) -> dict[str, Any]:
    return build_replay_report(archive_path=Path(args.archive_path), ledger_path=Path(args.ledger_path))


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
    _non_negative_arg(args, "paper_fee_bps", 4.0)
    _non_negative_arg(args, "paper_slippage_bps", 5.0)


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
    return "BTCUSDT" if "BTCUSDT" in tradable else (sorted(tradable)[0] if tradable else "")


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


if __name__ == "__main__":
    raise SystemExit(main())
