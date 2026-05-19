#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_RUNTIME_DIR = ROOT_DIR / ".runtime" / "auto-paper"
CREDENTIAL_NAME_RE = re.compile(r"BINANCE_.*(?:KEY|SECRET|SIGNATURE|LISTEN)", re.IGNORECASE)


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def credential_env_names() -> list[str]:
    return sorted(key for key in os.environ if CREDENTIAL_NAME_RE.search(key))


def command_env(runtime_dir: Path) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not CREDENTIAL_NAME_RE.search(key)}
    env["TRADECAT_AUTO_PAPER_RUNTIME_DIR"] = str(runtime_dir)
    env.setdefault("PYTHONUNBUFFERED", "1")
    return env


def run_json(command: list[str], *, runtime_dir: Path, timeout_seconds: float = 10.0) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            command,
            cwd=ROOT_DIR,
            env=command_env(runtime_dir),
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "error_code": "monitor_command_timeout",
            "error": {"code": "monitor_command_timeout", "message": str(exc), "command": command},
        }
    except OSError as exc:
        return {
            "ok": False,
            "error_code": "monitor_command_failed",
            "error": {"code": "monitor_command_failed", "message": str(exc), "command": command},
        }
    try:
        payload = json.loads(proc.stdout)
        if isinstance(payload, dict):
            payload.setdefault("_monitor_returncode", proc.returncode)
            return payload
    except json.JSONDecodeError:
        pass
    return {
        "ok": False,
        "error_code": "monitor_json_parse_failed",
        "error": {
            "code": "monitor_json_parse_failed",
            "message": "本地监控命令未返回 JSON object",
            "command": command,
            "returncode": proc.returncode,
            "stderr_tail": proc.stderr[-1000:],
            "stdout_tail": proc.stdout[-1000:],
        },
    }


def read_tail(path: Path, *, lines: int = 40, max_bytes: int = 65536) -> list[str]:
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - max_bytes), os.SEEK_SET)
            text = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    return text.splitlines()[-lines:]


def read_latest_jsonl(path: Path, *, max_bytes: int = 262144) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - max_bytes), os.SEEK_SET)
            text = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return {}
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def read_json_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def read_latest_decision_jsonl(path: Path, *, max_bytes: int = 1048576) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - max_bytes), os.SEEK_SET)
            text = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return {}
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("pipeline_report"), dict):
            return payload
    return {}


def _ops_check_ok(ops: dict[str, Any], check_id: str) -> bool:
    checks = ops.get("checks") if isinstance(ops.get("checks"), list) else []
    for item in checks:
        if isinstance(item, dict) and item.get("id") == check_id:
            return item.get("ok") is True
    return False


def _node(node_id: str, name: str, status: str, detail: str) -> dict[str, str]:
    return {"id": node_id, "name": name, "status": status, "detail": detail}


def build_dependency_health(
    *,
    status: dict[str, Any],
    health: dict[str, Any],
    ops: dict[str, Any],
    audit: dict[str, Any],
    latest_cycle: dict[str, Any],
    strategy_state: dict[str, Any],
) -> list[dict[str, str]]:
    heartbeat = health.get("heartbeat") if isinstance(health.get("heartbeat"), dict) else {}
    service_state = health.get("service_state") if isinstance(health.get("service_state"), dict) else {}
    archive = health.get("archive") if isinstance(health.get("archive"), dict) else {}
    ledger = health.get("ledger") if isinstance(health.get("ledger"), dict) else {}
    audit_journal = health.get("audit_journal") if isinstance(health.get("audit_journal"), dict) else audit
    safety = status.get("safety") if isinstance(status.get("safety"), dict) else {}
    runtime_ok = bool(status.get("running")) and bool(heartbeat.get("ok")) and not bool(heartbeat.get("stale"))
    no_new_signal = (
        service_state.get("last_error") == "no_events_available" or archive.get("last_action") == "SKIPPED_NO_EVENT"
    )
    thesis_path = str(status.get("agent_trade_thesis_path") or "")
    agent_sizing_required = bool(status.get("agent_sizing_required"))
    ops_ok = bool(ops.get("ok"))
    python_ok = _ops_check_ok(ops, "python_available") and _ops_check_ok(ops, "project_source_exists")
    runtime_paths_ok = all(
        _ops_check_ok(ops, check_id)
        for check_id in (
            "runtime_parent_exists",
            "runtime_parent_writable",
            "state_path_under_runtime",
            "ledger_path_under_runtime",
            "archive_path_under_runtime",
            "journal_path_under_runtime",
            "log_file_under_runtime",
            "pid_file_under_runtime",
        )
    )
    no_credential_env = _ops_check_ok(ops, "no_binance_credential_env_names")
    ledger_ok = bool(ledger.get("ok")) and bool(archive.get("ok"))
    audit_ok = bool(audit_journal.get("ok")) and bool(audit_journal.get("chain_valid"))
    public_readonly_ok = (
        safety.get("real_orders") is False
        and safety.get("signed_requests") is False
        and safety.get("reads_api_keys") is False
        and safety.get("binance_account_state") is False
    )
    portfolio_policy_path = str(status.get("portfolio_risk_policy_path") or "")
    kill_switch_path = str(status.get("paper_kill_switch_path") or "")
    strategy_policy = strategy_state.get("policy") if isinstance(strategy_state.get("policy"), dict) else {}
    strategy_enabled = bool(status.get("strategy_review_enabled")) and bool(strategy_state.get("enabled", False))
    latest_events = latest_cycle.get("events") if isinstance(latest_cycle.get("events"), dict) else {}
    input_change = latest_cycle.get("input_change") if isinstance(latest_cycle.get("input_change"), dict) else {}
    latest_event_error = latest_events.get("error") if isinstance(latest_events.get("error"), dict) else {}
    latest_event_rows = latest_events.get("events") if isinstance(latest_events.get("events"), list) else []
    source_ok = latest_events.get("ok")
    source_error_code = latest_events.get("error_code")
    source_error_status = latest_event_error.get("status")
    source_error_message = latest_event_error.get("message")
    source_detail = [
        f"source_ok={source_ok if source_ok is not None else '-'}",
        f"last_action={archive.get('last_action') or '-'}",
        f"trigger={input_change.get('trigger_reason') or '-'}",
        f"snapshot_changed={input_change.get('source_snapshot_changed') if input_change else '-'}",
    ]
    if latest_event_rows:
        source_detail.append(f"source_rows={len(latest_event_rows)}")
    if source_error_code:
        source_detail.append(f"source_error={source_error_code}")
    if source_error_status is not None:
        source_detail.append(f"source_http_status={source_error_status}")
    if source_error_message:
        source_detail.append(f"source_message={source_error_message}")
    return [
        _node(
            "operator_supervisor",
            "Hermes/operator 运行看护",
            "ok" if runtime_ok else "error",
            f"auto-paper running={bool(status.get('running'))}; heartbeat_stale={bool(heartbeat.get('stale'))}",
        ),
        _node(
            "skill_package",
            "skills/tradecat-public Skill 包",
            "ok" if ops_ok and runtime_paths_ok else "error",
            f"ops_check={ops_ok}; runtime_paths_ok={runtime_paths_ok}",
        ),
        _node(
            "python_project",
            "仓库根 Python 项目环境",
            "ok" if python_ok else "error",
            f"python_available={_ops_check_ok(ops, 'python_available')}; project_source_exists={_ops_check_ok(ops, 'project_source_exists')}",
        ),
        _node(
            "sheet_signal_source",
            "公开在线表格信号源",
            "warn" if no_new_signal else "ok",
            "; ".join(source_detail),
        ),
        _node(
            "agent_market_context",
            "Agent-supplied Binance public market context",
            "warn" if agent_sizing_required else "ok",
            "等待外部 Agent/Hermes thesis；若启用默认 runtime profile 会自动补齐 paper-only sizing/exits"
            if agent_sizing_required
            else "Agent thesis 或默认 runtime profile 已进入 paper/watch 链路",
        ),
        _node(
            "context_audit",
            "context-audit 契约审计",
            "ok",
            "契约审计可用；关闭默认 runtime profile 时缺 Agent thesis 会结构化等待/拒绝"
            if agent_sizing_required
            else "Agent context 已通过链路进入 paper",
        ),
        _node(
            "trade_thesis",
            "Agent 自主 thesis / sizing / exits",
            "warn" if agent_sizing_required else "ok",
            "等待外部 Agent thesis，或重新启用默认 runtime paper autonomy profile"
            if agent_sizing_required
            else f"paper_sizing_source={(status.get('paper_sizing') or {}).get('source') if isinstance(status.get('paper_sizing'), dict) else '-'}; thesis_path={'configured' if thesis_path else 'inline_or_runtime'}",
        ),
        _node(
            "risk_controls",
            "可选本地组合约束 / kill switch",
            "ok",
            (
                "用户显式约束已配置: "
                f"portfolio_policy={'configured' if portfolio_policy_path else 'none'}; "
                f"kill_switch={'configured' if kill_switch_path else 'none'}"
            )
            if portfolio_policy_path or kill_switch_path
            else "默认不启用本地组合约束；Agent thesis 直接驱动 paper/watch，安全边界单独强制",
        ),
        _node(
            "strategy_iteration",
            "paper outcome 自我迭代过滤",
            "ok" if strategy_enabled else "warn",
            (
                f"state={strategy_state.get('status') or '-'}; "
                f"blocked_symbols={len(strategy_policy.get('blocked_symbols') or [])}; "
                f"blocked_signal_types={len(strategy_policy.get('blocked_signal_types') or [])}; "
                f"blocked_sides={','.join(strategy_policy.get('blocked_sides') or []) or '-'}; "
                f"max_open_positions={strategy_policy.get('max_open_positions') or '-'}"
            )
            if strategy_state
            else "strategy_state.json 尚未生成；等待下一轮 strategy-review",
        ),
        _node(
            "auto_paper_loop",
            "auto-paper run-loop",
            "ok" if runtime_ok else "error",
            f"cycles_attempted={service_state.get('cycles_attempted')}; cycle_count={archive.get('cycle_count')}",
        ),
        _node(
            "ledger_archive_audit",
            "paper ledger / cycle archive / audit journal",
            "ok" if ledger_ok and audit_ok else "error",
            f"ledger_ok={ledger_ok}; archive_ok={bool(archive.get('ok'))}; audit_chain_valid={bool(audit_journal.get('chain_valid'))}",
        ),
        _node(
            "reports_alerts",
            "health / daily / alert 报告",
            "ok" if bool(health.get("ok")) else "error",
            f"health_status={health.get('status') or '-'}; alerts={len(health.get('alerts') or [])}",
        ),
        _node(
            "safety_boundary",
            "public-readonly + paper/watch 安全边界",
            "ok" if public_readonly_ok and no_credential_env else "error",
            f"real_orders={safety.get('real_orders')}; signed_requests={safety.get('signed_requests')}; reads_api_keys={safety.get('reads_api_keys')}; credential_env_clean={no_credential_env}",
        ),
    ]


def build_risk_state(health: dict[str, Any]) -> dict[str, Any]:
    ledger = health.get("ledger") if isinstance(health.get("ledger"), dict) else {}
    summary = ledger.get("summary") if isinstance(ledger.get("summary"), dict) else {}
    equity = summary.get("equity_usdt")
    initial = summary.get("initial_balance_usdt") or 1000.0
    try:
        equity_value = float(equity)
        initial_value = float(initial)
    except (TypeError, ValueError):
        equity_value = None
        initial_value = None
    drawdown_usdt = None
    drawdown_pct = None
    if equity_value is not None and initial_value and initial_value > 0:
        drawdown_usdt = max(0.0, initial_value - equity_value)
        drawdown_pct = drawdown_usdt / initial_value * 100.0
    alerts = health.get("alerts") if isinstance(health.get("alerts"), list) else []
    return {
        "schema": "tradecat_auto.paper_web_monitor_risk_state.v1",
        "schema_version": "1.0.0",
        "ok": bool(health.get("ok")) and not alerts,
        "equity_usdt": equity_value,
        "initial_balance_usdt": initial_value,
        "drawdown_usdt": drawdown_usdt,
        "drawdown_pct": drawdown_pct,
        "open_positions_count": summary.get("open_positions_count"),
        "unrealized_pnl_usdt": summary.get("unrealized_pnl_usdt"),
        "alerts": alerts,
        "latest_ledger_update_at": summary.get("last_updated_at"),
        "limitations": [
            "derived from local paper ledger and health report only",
            "not a Binance account, order, liquidation, or exchange risk signal",
            "mark-to-market freshness depends on auto-paper cycle behavior and available public market data",
        ],
    }


def build_decision_text(latest_cycle: dict[str, Any]) -> dict[str, Any]:
    pipeline = latest_cycle.get("pipeline_report") if isinstance(latest_cycle.get("pipeline_report"), dict) else {}
    if not pipeline:
        return {
            "schema": "tradecat_auto.paper_web_monitor_decision_text.v1",
            "schema_version": "1.0.0",
            "ok": False,
            "error_code": "decision_text_unavailable",
            "text": "当前还没有可展示的 Agent/TradeCat 决策产物。等待 auto-paper 写入下一轮 cycles.jsonl。",
            "sections": [],
            "provenance": {
                "source": ".runtime/auto-paper/cycles.jsonl",
                "cycle_schema": str(latest_cycle.get("schema") or ""),
            },
            "safety": _monitor_safety_boundary(),
            "limitations": ["dashboard shows auditable decision artifacts, not hidden model chain-of-thought"],
        }
    event = _decision_signal_event(latest_cycle, pipeline)
    thesis = _as_dict(pipeline.get("agent_trade_thesis"))
    signal = _as_dict(pipeline.get("signal"))
    strategy = _as_dict(pipeline.get("strategy_intent"))
    risk = _as_dict(pipeline.get("risk_decision"))
    execution = _as_dict(pipeline.get("paper_execution"))
    sizing = _as_dict(pipeline.get("paper_sizing"))
    explanation = _as_dict(strategy.get("explanation"))
    metrics = _as_dict(signal.get("metrics_used") or explanation.get("metrics_used"))
    safety = _as_dict(pipeline.get("safety")) or _monitor_safety_boundary()
    sections = [
        _decision_section(
            "输入信号",
            [
                ("来源", event.get("source_dataset_key")),
                ("来源集合", _join_text_list(event.get("source_dataset_keys"))),
                (
                    "时间",
                    event.get("source_time_bj") or latest_cycle.get("generated_at") or pipeline.get("generated_at"),
                ),
                ("事件 ID", event.get("event_id")),
                ("币种", event.get("symbol")),
                ("周期", event.get("period")),
                ("类型", event.get("signal_type")),
                ("内容", event.get("content")),
                ("原始字段", _format_key_values(event.get("source_values"))),
                ("关联异动面板", _format_related_anomaly(event.get("related_anomaly_panel"))),
            ],
        ),
        _decision_section(
            "本轮输入候选",
            [
                ("决策事件数", _event_count(_as_dict(latest_cycle.get("events")).get("events"))),
                ("触发原因", _format_input_change(latest_cycle.get("input_change"))),
                ("决策事件列表", _format_event_rows(_as_dict(latest_cycle.get("events")).get("events"))),
                ("信号流抓取数", _as_dict(pipeline.get("signal_flow_events")).get("count")),
                ("信号流去重丢弃数", _as_dict(pipeline.get("signal_flow_events")).get("duplicate_count")),
                ("信号流前 10", _format_event_rows(_as_dict(pipeline.get("signal_flow_events")).get("first_10"))),
                ("异动面板抓取数", _as_dict(pipeline.get("anomaly_symbols")).get("count")),
                ("异动面板候选行数", _as_dict(pipeline.get("anomaly_symbols")).get("row_count")),
                ("异动面板榜单", _format_sections(_as_dict(pipeline.get("anomaly_symbols")).get("sections"))),
                (
                    "异动面板前 10 行",
                    _format_anomaly_rows(_as_dict(pipeline.get("anomaly_symbols")).get("first_10_rows")),
                ),
                (
                    "异动面板去重前 10 币种",
                    _format_anomaly_rows(_as_dict(pipeline.get("anomaly_symbols")).get("first_10")),
                ),
            ],
        ),
        _decision_section(
            "Agent thesis",
            [
                ("来源", _thesis_source(thesis)),
                ("币种", thesis.get("symbol") or pipeline.get("selected_symbol") or signal.get("symbol")),
                ("方向", thesis.get("direction") or strategy.get("direction") or signal.get("direction")),
                ("信心", _format_percent(thesis.get("confidence"))),
                ("理由", thesis.get("rationale")),
                ("风险备注", _join_text_list(thesis.get("risk_notes"))),
                ("限制", _join_text_list(thesis.get("limitations"))),
            ],
        ),
        _decision_section(
            "信号评分",
            [
                ("分数", signal.get("score")),
                ("可交易候选", signal.get("tradable_candidate")),
                ("正向因子", _join_text_list(signal.get("positive_factors"))),
                ("负向因子", _join_text_list(signal.get("negative_factors"))),
                ("不交易原因", _join_text_list(signal.get("do_not_trade_reasons"))),
                ("关键指标", _format_metrics(metrics)),
            ],
        ),
        _decision_section(
            "策略与退出计划",
            [
                ("动作", strategy.get("action")),
                ("入场类型", strategy.get("entry_type")),
                ("参考入场价", strategy.get("entry_price")),
                ("止损/失效价", strategy.get("invalidation_price")),
                ("止盈价", strategy.get("take_profit_price")),
                ("最长持仓分钟", strategy.get("max_holding_minutes")),
                ("退出计划来源", strategy.get("exit_plan_source")),
                ("退出理由", strategy.get("exit_rationale")),
                ("策略标签", _join_text_list(strategy.get("strategy_tags"))),
            ],
        ),
        _decision_section(
            "风控结论",
            [
                ("决定", risk.get("decision")),
                ("拒绝/提示原因", _join_text_list(risk.get("reasons"))),
                ("仓位来源", _as_dict(risk.get("policy")).get("sizing_source") or sizing.get("source")),
                (
                    "请求保证金 USDT",
                    _as_dict(risk.get("policy")).get("requested_margin_usdt") or sizing.get("requested_margin_usdt"),
                ),
                ("纸面杠杆", risk.get("paper_leverage") or sizing.get("paper_leverage")),
                ("约束", _join_text_list(risk.get("constraints"))),
            ],
        ),
        _decision_section(
            "纸面执行",
            [
                ("状态", execution.get("status")),
                ("方向", execution.get("side")),
                ("名义金额 USDT", execution.get("notional_usdt")),
                ("保证金 USDT", execution.get("margin_usdt")),
                ("数量", execution.get("quantity")),
                ("纸面执行 ID", execution.get("paper_execution_id")),
                ("执行拒绝原因", _join_text_list(execution.get("reasons"))),
            ],
        ),
    ]
    text = "\n\n".join(f"{item['title']}\n{item['text']}" for item in sections if item["text"])
    return {
        "schema": "tradecat_auto.paper_web_monitor_decision_text.v1",
        "schema_version": "1.0.0",
        "ok": True,
        "error_code": None,
        "symbol": thesis.get("symbol") or pipeline.get("selected_symbol") or signal.get("symbol"),
        "direction": thesis.get("direction") or strategy.get("direction") or signal.get("direction"),
        "decision": risk.get("decision"),
        "paper_execution_status": execution.get("status"),
        "text": text,
        "sections": sections,
        "provenance": {
            "source": ".runtime/auto-paper/cycles.jsonl",
            "cycle_schema": str(latest_cycle.get("schema") or ""),
            "pipeline_schema": str(pipeline.get("schema") or ""),
            "paper_execution_id": str(execution.get("paper_execution_id") or ""),
            "event_id": str(event.get("event_id") or ""),
        },
        "safety": {
            **_monitor_safety_boundary(),
            **safety,
            "real_orders": False,
            "signed_requests": False,
            "reads_api_keys": False,
            "binance_account_state": False,
        },
        "limitations": ["dashboard shows auditable decision artifacts, not hidden model chain-of-thought"],
    }


def build_snapshot(runtime_dir: Path) -> dict[str, Any]:
    ledger_path = runtime_dir / "paper_ledger.json"
    journal_path = runtime_dir / "paper_audit.sqlite3"
    log_path = runtime_dir / "paper-run-loop.log"
    archive_path = runtime_dir / "cycles.jsonl"
    strategy_state_path = runtime_dir / "strategy_state.json"
    strategy_review_report_path = runtime_dir / "strategy-review-latest.json"
    latest_cycle = read_latest_jsonl(archive_path)
    latest_decision_cycle = read_latest_decision_jsonl(archive_path)
    strategy_state = read_json_file(strategy_state_path)
    strategy_review = read_json_file(strategy_review_report_path)
    status = run_json(["bash", "scripts/start-auto-paper.sh", "status", "--json"], runtime_dir=runtime_dir)
    health = run_json(["bash", "scripts/start-auto-paper.sh", "health", "--json"], runtime_dir=runtime_dir)
    ops = run_json(["bash", "scripts/start-auto-paper.sh", "ops-check", "--json"], runtime_dir=runtime_dir)
    paper = run_json(
        [
            "bash",
            "scripts/run-tradecat.sh",
            "auto",
            "paper-report",
            "--ledger-path",
            str(ledger_path),
            "--json",
        ],
        runtime_dir=runtime_dir,
    )
    audit = run_json(
        [
            "bash",
            "scripts/run-tradecat.sh",
            "auto",
            "audit-journal",
            "--journal-path",
            str(journal_path),
            "--json",
        ],
        runtime_dir=runtime_dir,
    )
    return {
        "schema": "tradecat_auto.paper_web_monitor_snapshot.v1",
        "schema_version": "1.0.0",
        "ok": bool(health.get("ok")) and bool(status.get("running")),
        "generated_at": utc_now(),
        "mode": "paper",
        "runtime": {
            "runtime_dir": str(runtime_dir),
            "ledger_path": str(ledger_path),
            "journal_path": str(journal_path),
            "log_path": str(log_path),
            "strategy_state_path": str(strategy_state_path),
            "strategy_review_report_path": str(strategy_review_report_path),
        },
        "status": status,
        "health": health,
        "ops": ops,
        "paper": paper,
        "audit": audit,
        "latest_cycle": latest_cycle,
        "latest_decision_cycle": latest_decision_cycle,
        "strategy_state": strategy_state,
        "strategy_review": strategy_review,
        "risk_state": build_risk_state(health),
        "decision_text": build_decision_text(latest_decision_cycle or latest_cycle),
        "dependency_health": build_dependency_health(
            status=status,
            health=health,
            ops=ops,
            audit=audit,
            latest_cycle=latest_cycle,
            strategy_state=strategy_state,
        ),
        "log_tail": read_tail(log_path),
        "monitor_environment": {
            "credential_env_names_present": credential_env_names(),
            "credential_env_values_read": False,
        },
        "safety": {
            **_monitor_safety_boundary(),
        },
    }


def _monitor_safety_boundary() -> dict[str, bool]:
    return {
        "public_readonly_market_data": True,
        "paper_or_watch_only": True,
        "real_orders": False,
        "signed_requests": False,
        "reads_api_keys": False,
        "binance_account_state": False,
    }


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _join_text_list(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value if str(item))
    return str(value) if value not in (None, "") else ""


def _format_percent(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if 0 <= number <= 1:
        return f"{number * 100:.2f}%"
    return f"{number:.2f}"


def _format_metrics(metrics: dict[str, Any]) -> str:
    if not metrics:
        return ""
    return ", ".join(f"{key}={value}" for key, value in sorted(metrics.items()) if value not in (None, ""))


def _thesis_source(thesis: dict[str, Any]) -> str:
    provenance = _as_dict(thesis.get("provenance"))
    if provenance.get("paper_autonomy_profile"):
        return "paper_autonomy_profile 合成的 paper-only Agent thesis"
    if thesis:
        return "外部 Agent/Hermes thesis"
    return "未提供 thesis"


def _decision_signal_event(latest_cycle: dict[str, Any], pipeline: dict[str, Any]) -> dict[str, Any]:
    event = _as_dict(latest_cycle.get("latest_event") or pipeline.get("latest_event"))
    if str(event.get("source_dataset_key") or "") in {"signal_flow", "anomaly_panel"}:
        return event
    enrichment = _as_dict(pipeline.get("enrichment"))
    source_values = _as_dict(enrichment.get("source_values"))
    symbol = str(enrichment.get("symbol") or pipeline.get("selected_symbol") or "").upper().strip()
    if not source_values and not symbol:
        return event
    return {
        "schema": "tradecat_auto.anomaly_signal_event.v1",
        "schema_version": "1.0.0",
        "event_id": str(event.get("event_id") or ""),
        "source_dataset_key": "anomaly_panel",
        "row_index": enrichment.get("first_row_index") or source_values.get("序号") or "",
        "source_time_bj": _source_time_from_values(source_values) or event.get("source_time_bj"),
        "symbol": symbol,
        "raw_symbol": enrichment.get("raw_symbol") or source_values.get("交易对") or symbol,
        "content": _format_anomaly_source_text(symbol, source_values),
        "source_values": source_values,
        "provenance": {
            "source": "tradecat_auto.paper_web_monitor.decision_signal_event",
            "derived_from": "pipeline_report.enrichment.source_values",
            "legacy_latest_event_source": str(event.get("source_dataset_key") or ""),
        },
    }


def _source_time_from_values(values: dict[str, Any]) -> str:
    for key in ("时间(北京)", "更新时间", "时间", "time", "source_time_bj", "updated_at", "timestamp"):
        text = str(values.get(key) or "").strip()
        if text:
            return text
    return ""


def _format_anomaly_source_text(symbol: str, values: dict[str, Any]) -> str:
    if not values:
        return f"{symbol} 异动面板信号".strip()
    priority = (
        "交易对",
        "合约代码",
        "币种符号",
        "5m量变化率",
        "5m额变化率",
        "量额背离",
        "量异常强度",
        "额异常强度",
        "现持仓额",
    )
    pairs = []
    used = set()
    for key in priority:
        value = str(values.get(key) or "").strip()
        if value:
            pairs.append(f"{key}={value}")
            used.add(key)
    for key, value in values.items():
        if key in used:
            continue
        text = str(value or "").strip()
        if text:
            pairs.append(f"{key}={text}")
    return f"{symbol} 异动面板信号: {'; '.join(pairs)}".strip()


def _format_key_values(value: Any) -> str:
    values = _as_dict(value)
    return "; ".join(f"{key}={item}" for key, item in values.items() if str(item or "").strip())


def _format_related_anomaly(value: Any) -> str:
    related = _as_dict(value)
    if not related:
        return ""
    source_values = _format_key_values(related.get("source_values"))
    prefix = f"row={related.get('row_index')}; symbol={related.get('normalized_symbol')}"
    return f"{prefix}; {source_values}" if source_values else prefix


def _format_input_change(value: Any) -> str:
    change = _as_dict(value)
    if not change:
        return ""
    parts = [
        f"trigger={change.get('trigger_reason') or '-'}",
        f"source_snapshot_changed={change.get('source_snapshot_changed')}",
        f"signal_flow_changed={change.get('signal_flow_changed')}",
        f"anomaly_panel_changed={change.get('anomaly_panel_changed')}",
        f"maintenance_due={change.get('maintenance_due')}",
    ]
    event_id = str(change.get("new_signal_flow_event_id") or "").strip()
    if event_id:
        parts.append(f"new_signal_flow_event_id={event_id}")
    return "; ".join(parts)


def _event_count(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def _format_event_rows(value: Any) -> str:
    if not isinstance(value, list) or not value:
        return ""
    lines: list[str] = []
    for index, item in enumerate(value[:10], start=1):
        if not isinstance(item, dict):
            continue
        source = str(item.get("source_dataset_key") or "").strip()
        symbol = str(item.get("symbol") or item.get("normalized_symbol") or item.get("raw_symbol") or "").strip()
        time_text = str(item.get("source_time_bj") or "").strip()
        period = str(item.get("period") or "").strip()
        signal_type = str(item.get("signal_type") or "").strip()
        content = str(item.get("content") or "").strip()
        raw_values = _format_key_values(item.get("source_values"))
        parts = [
            f"#{index}",
            f"source={source}" if source else "",
            f"symbol={symbol}" if symbol else "",
            f"time={time_text}" if time_text else "",
            f"period={period}" if period else "",
            f"type={signal_type}" if signal_type else "",
            f"content={content}" if content else "",
            f"raw={raw_values}" if raw_values else "",
        ]
        lines.append("; ".join(part for part in parts if part))
    return "\n".join(lines)


def _format_anomaly_rows(value: Any) -> str:
    if not isinstance(value, list) or not value:
        return ""
    lines: list[str] = []
    for index, item in enumerate(value[:10], start=1):
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("normalized_symbol") or item.get("raw_symbol") or "").strip()
        row_index = item.get("row_index") or item.get("first_row_index")
        raw_values = _format_key_values(item.get("source_values"))
        prefix = f"#{index}; row={row_index or '-'}; symbol={symbol or '-'}"
        lines.append(f"{prefix}; {raw_values}" if raw_values else prefix)
    return "\n".join(lines)


def _format_sections(value: Any) -> str:
    if not isinstance(value, list) or not value:
        return ""
    parts = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        count = item.get("row_count")
        if name:
            parts.append(f"{name}({count})")
    return ", ".join(parts)


def _decision_section(title: str, pairs: list[tuple[str, Any]]) -> dict[str, str]:
    lines = [f"{label}: {value}" for label, value in pairs if value not in (None, "", [])]
    return {"title": title, "text": "\n".join(lines)}


def html_page() -> bytes:
    body = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TradeCat 纸面交易监控</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f7f8fa;
      --panel: #ffffff;
      --text: #18212f;
      --muted: #667085;
      --line: #d8dee8;
      --ok: #0f7b4f;
      --warn: #a15c00;
      --bad: #ad1f2b;
      --accent: #155eef;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.45 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    main { max-width: 1180px; margin: 0 auto; padding: 20px; }
    header { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; margin-bottom: 16px; }
    h1 { margin: 0; font-size: 24px; font-weight: 700; letter-spacing: 0; }
    .sub { color: var(--muted); margin-top: 4px; }
    .grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
    .wide { grid-column: span 2; }
    .full { grid-column: 1 / -1; }
    section {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      min-width: 0;
    }
    h2 { margin: 0 0 10px; font-size: 14px; color: var(--muted); font-weight: 650; letter-spacing: 0; }
    .metric { font-size: 26px; font-weight: 750; letter-spacing: 0; overflow-wrap: anywhere; }
    .label { color: var(--muted); }
    .pill { display: inline-flex; align-items: center; min-height: 24px; padding: 2px 8px; border-radius: 999px; font-weight: 700; }
    .ok { color: var(--ok); background: #e9f7ef; }
    .warn { color: var(--warn); background: #fff2d8; }
    .bad { color: var(--bad); background: #fde8ea; }
    .row { display: flex; justify-content: space-between; gap: 12px; padding: 6px 0; border-bottom: 1px solid #edf0f5; }
    .row:last-child { border-bottom: 0; }
    .value { text-align: right; overflow-wrap: anywhere; }
    .dependency-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
    .dependency-item { border: 1px solid #edf0f5; border-radius: 8px; padding: 10px; min-width: 0; }
    .dependency-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 6px; }
    .dependency-title { font-weight: 700; overflow-wrap: anywhere; }
    .dependency-detail { color: var(--muted); font-size: 12px; overflow-wrap: anywhere; }
    .decision-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
    .decision-item { border: 1px solid #edf0f5; border-radius: 8px; padding: 10px; min-width: 0; }
    .decision-title { font-weight: 700; margin-bottom: 6px; color: var(--accent); }
    .decision-item pre { max-height: 220px; color: var(--text); }
    pre {
      margin: 0;
      overflow: auto;
      white-space: pre-wrap;
      word-break: break-word;
      font: 12px/1.45 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      max-height: 360px;
    }
    button {
      border: 1px solid var(--line);
      background: var(--panel);
      color: var(--text);
      border-radius: 6px;
      min-height: 34px;
      padding: 6px 10px;
      cursor: pointer;
    }
    @media (max-width: 900px) {
      .grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .wide { grid-column: 1 / -1; }
    }
    @media (max-width: 560px) {
      main { padding: 12px; }
      header { display: block; }
      .grid { grid-template-columns: 1fr; }
      .row { display: block; }
      .value { text-align: left; margin-top: 2px; }
      .dependency-list { grid-template-columns: 1fr; }
      .decision-list { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
<main>
  <header>
    <div>
      <h1>TradeCat 纸面交易监控</h1>
      <div class="sub" id="subtitle">正在加载</div>
    </div>
    <button type="button" id="refresh">刷新</button>
  </header>
  <div class="grid">
    <section><h2>服务状态</h2><div class="metric" id="service">-</div><div class="label" id="pid">-</div></section>
    <section><h2>健康状态</h2><div class="metric" id="health">-</div><div class="label" id="heartbeat">-</div></section>
    <section><h2>持仓数量</h2><div class="metric" id="open">-</div><div class="label" id="equity">-</div></section>
    <section><h2>循环次数</h2><div class="metric" id="cycles">-</div><div class="label" id="lastAction">-</div></section>
    <section class="wide"><h2>安全边界</h2><div id="safety"></div></section>
    <section class="wide"><h2>纸面账本</h2><div id="ledger"></div></section>
    <section class="wide"><h2>回撤/告警</h2><div id="riskState"></div></section>
    <section class="wide"><h2>审计日志</h2><div id="audit"></div></section>
    <section class="wide"><h2>运维预检</h2><div id="ops"></div></section>
    <section class="full"><h2>依赖链健康</h2><div id="dependencyHealth" class="dependency-list"></div></section>
    <section class="full"><h2>AI 文本决策</h2><div id="decisionSummary"></div><div id="decisionText" class="decision-list"></div></section>
    <section class="full"><h2>运行日志尾部</h2><pre id="log">正在加载</pre></section>
  </div>
</main>
<script>
const $ = (id) => document.getElementById(id);
const TEXT = {
  running: "运行中",
  stopped: "未运行",
  healthy: "健康",
  degraded: "降级",
  failed: "失败",
  ok: "正常",
  warn: "警告",
  error: "异常",
  unknown: "未知",
  SKIPPED_NO_EVENT: "无新信号，跳过",
  SKIPPED_STALE_EVENT: "信号过期，跳过",
  SKIPPED_DUPLICATE_EVENT: "重复信号，跳过",
  PROCESSED: "已处理",
  agent_required_missing: "等待 Agent thesis",
  service_environment: "服务环境显式提供",
  true: "是",
  false: "否"
};
function cls(ok, warn=false) { return ok ? "pill ok" : (warn ? "pill warn" : "pill bad"); }
function safe(v, fallback="-") { return v === undefined || v === null || v === "" ? fallback : v; }
function escapeHtml(v) {
  return String(safe(v)).replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  }[ch]));
}
function boolText(v) { return v === true ? TEXT.true : (v === false ? TEXT.false : safe(v)); }
function statusText(v) { return TEXT[v] || safe(v); }
function statusClass(status) {
  if (status === "ok") return "pill ok";
  if (status === "warn" || status === "unknown") return "pill warn";
  return "pill bad";
}
function fixed(v, digits=4) { return Number.isFinite(v) ? v.toFixed(digits) : "-"; }
function row(label, value) { return `<div class="row"><span class="label">${escapeHtml(label)}</span><span class="value">${escapeHtml(value)}</span></div>`; }
function dependencyNode(item) {
  const status = item && item.status || "unknown";
  return `<div class="dependency-item">
    <div class="dependency-head"><span class="dependency-title">${escapeHtml(item && item.name)}</span><span class="${statusClass(status)}">${escapeHtml(statusText(status))}</span></div>
    <div class="dependency-detail">${escapeHtml(item && item.detail)}</div>
  </div>`;
}
function decisionNode(item) {
  return `<div class="decision-item">
    <div class="decision-title">${escapeHtml(item && item.title)}</div>
    <pre>${escapeHtml(item && item.text)}</pre>
  </div>`;
}
async function refresh() {
  const res = await fetch("/api/snapshot", {cache: "no-store"});
  const data = await res.json();
  const status = data.status || {};
  const health = data.health || {};
  const heartbeat = health.heartbeat || {};
  const ledger = (health.ledger && health.ledger.summary) || (data.paper && data.paper.summary) || {};
  const archive = health.archive || {};
  const audit = data.audit || {};
  const ops = data.ops || {};
  const risk = data.risk_state || {};
  const decision = data.decision_text || {};
  $("subtitle").textContent = `生成时间=${safe(data.generated_at)} 运行目录=${safe(data.runtime && data.runtime.runtime_dir)}`;
  $("service").innerHTML = `<span class="${cls(status.running)}">${status.running ? TEXT.running : TEXT.stopped}</span>`;
  $("pid").textContent = `进程=${safe(status.pid)} 事件=${statusText(status.event)}`;
  $("health").innerHTML = `<span class="${cls(health.ok, heartbeat.stale)}">${statusText(health.status)}</span>`;
  $("heartbeat").textContent = `心跳=${statusText(heartbeat.status)} 年龄=${fixed(heartbeat.age_seconds, 1)}秒 上限=${fixed(heartbeat.max_age_seconds, 1)}秒`;
  $("open").textContent = safe(ledger.open_positions_count);
  $("equity").textContent = `权益=${fixed(ledger.equity_usdt)} 未实现=${fixed(ledger.unrealized_pnl_usdt)}`;
  $("cycles").textContent = safe(archive.cycle_count);
  $("lastAction").textContent = `最近动作=${statusText(archive.last_action)}`;
  const safety = data.safety || {};
  $("safety").innerHTML = [
    row("真实下单", boolText(safety.real_orders)),
    row("签名请求", boolText(safety.signed_requests)),
    row("读取 API Key", boolText(safety.reads_api_keys)),
    row("读取 Binance 账户状态", boolText(safety.binance_account_state)),
    row("检测到凭证环境变量名", (data.monitor_environment && data.monitor_environment.credential_env_names_present || []).join(", ") || "-")
  ].join("");
  $("ledger").innerHTML = [
    row("现金余额 USDT", fixed(ledger.cash_balance_usdt)),
    row("账户权益 USDT", fixed(ledger.equity_usdt)),
    row("已实现盈亏 USDT", fixed(ledger.realized_pnl_usdt)),
    row("未实现盈亏 USDT", fixed(ledger.unrealized_pnl_usdt)),
    row("纸面订单数", ledger.paper_orders_count),
    row("成交记录数", ledger.fills_count)
  ].join("");
  $("riskState").innerHTML = [
    row("当前回撤 USDT", fixed(risk.drawdown_usdt)),
    row("当前回撤百分比", Number.isFinite(risk.drawdown_pct) ? `${fixed(risk.drawdown_pct, 4)}%` : "-"),
    row("未实现盈亏 USDT", fixed(risk.unrealized_pnl_usdt)),
    row("健康告警", (risk.alerts || []).join(", ") || "-"),
    row("账本更新时间", risk.latest_ledger_update_at)
  ].join("");
  $("audit").innerHTML = [
    row("审计状态", boolText(audit.ok)),
    row("哈希链有效", boolText(audit.chain_valid)),
    row("记录数量", audit.record_count),
    row("运行批次数", audit.run_count),
    row("最新记录 SHA256", audit.latest_record_sha256)
  ].join("");
  const opsRows = [
    row("预检通过", boolText(ops.ok)),
    row("阻塞检查", (ops.blocking_checks || []).join(", ") || "-")
  ];
  if (status.agent_trade_thesis_configured || (status.paper_sizing && status.paper_sizing.source && status.paper_sizing.source !== "agent_required_missing")) {
    opsRows.push(row("Agent thesis", status.agent_trade_thesis_configured ? "已配置" : "运行内联"));
    opsRows.push(row("纸面 sizing 来源", statusText(status.paper_sizing && status.paper_sizing.source)));
  }
  if (status.paper_autonomy_profile_configured) {
    opsRows.push(row("paper autonomy profile", status.paper_autonomy_profile_defaulted ? "默认 runtime profile" : "显式配置"));
  }
  $("ops").innerHTML = opsRows.join("");
  $("dependencyHealth").innerHTML = (data.dependency_health || []).map(dependencyNode).join("") || row("状态", "无依赖链数据");
  $("decisionSummary").innerHTML = [
    row("状态", decision.ok ? "可展示" : "暂无决策文本"),
    row("币种", decision.symbol),
    row("方向", decision.direction),
    row("风控决定", decision.decision),
    row("纸面执行状态", decision.paper_execution_status),
    row("来源", decision.provenance && decision.provenance.source),
    row("说明", (decision.limitations || []).join(", ") || "-")
  ].join("");
  $("decisionText").innerHTML = (decision.sections || []).map(decisionNode).join("") || `<pre>${escapeHtml(decision.text || "暂无文本决策")}</pre>`;
  $("log").textContent = (data.log_tail || []).join("\n") || "(空)";
}
$("refresh").addEventListener("click", refresh);
refresh().catch((err) => { $("subtitle").textContent = String(err); });
setInterval(() => refresh().catch(() => {}), 5000);
</script>
</body>
</html>
"""
    return body.encode("utf-8")


class MonitorHandler(BaseHTTPRequestHandler):
    server_version = "TradeCatPaperMonitor/1.0"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_bytes(HTTPStatus.OK, html_page(), content_type="text/html; charset=utf-8")
            return
        if parsed.path == "/api/snapshot":
            payload = build_snapshot(self.server.runtime_dir)  # type: ignore[attr-defined]
            self.send_json(HTTPStatus.OK, payload)
            return
        if parsed.path == "/healthz":
            self.send_json(HTTPStatus.OK, {"ok": True, "generated_at": utc_now()})
            return
        self.send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error_code": "not_found"})

    def do_HEAD(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/api/snapshot", "/healthz"}:
            self.send_response(HTTPStatus.OK)
            self.end_headers()
            return
        self.send_response(HTTPStatus.NOT_FOUND)
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        timestamp = utc_now()
        print(f"{timestamp} {self.address_string()} {format % args}", flush=True)

    def send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        self.send_bytes(
            status,
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            content_type="application/json; charset=utf-8",
        )

    def send_bytes(self, status: HTTPStatus, payload: bytes, *, content_type: str) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'",
            )
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            return


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="启动本地只读 TradeCat 纸面交易监控页面。")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址，默认 127.0.0.1")
    parser.add_argument("--port", type=int, default=8765, help="监听端口，默认 8765")
    parser.add_argument("--runtime-dir", type=Path, default=DEFAULT_RUNTIME_DIR, help="auto-paper 运行态目录。")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    runtime_dir = args.runtime_dir.resolve()
    server = ThreadingHTTPServer((args.host, args.port), MonitorHandler)
    server.runtime_dir = runtime_dir  # type: ignore[attr-defined]
    print(f"tradecat_auto.paper_web_monitor 正在监听 http://{args.host}:{args.port}/ 运行态={runtime_dir}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
