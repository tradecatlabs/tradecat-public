from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

from tradecat_auto.audit_journal import append_audit_record

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path("scripts/start-auto-paper.sh")
WEB_MONITOR_SCRIPT = Path("scripts/serve-auto-paper-monitor.py")


def load_web_monitor_module() -> object:
    spec = importlib.util.spec_from_file_location("tradecat_auto_web_monitor", PROJECT_ROOT / WEB_MONITOR_SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def run_service_script(args: list[str], *, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=PROJECT_ROOT,
        env={**os.environ, **env},
        text=True,
        capture_output=True,
        check=False,
    )


def make_fake_systemctl(tmp_path: Path) -> tuple[Path, Path]:
    log_path = tmp_path / "systemctl.log"
    fake = tmp_path / "systemctl"
    fake.write_text(
        '#!/usr/bin/env bash\nprintf \'%s\\n\' "$*" >>"$FAKE_SYSTEMCTL_LOG"\nexit 0\n',
        encoding="utf-8",
    )
    fake.chmod(0o755)
    return fake, log_path


def test_auto_paper_service_status_reports_not_running_with_stable_json(tmp_path: Path) -> None:
    env = {"TRADECAT_AUTO_PAPER_RUNTIME_DIR": str(tmp_path / "run")}

    proc = run_service_script(["status", "--json"], env=env)

    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["schema"] == "tradecat_auto.paper_service_status.v1"
    assert payload["schema_version"] == "1.0.0"
    assert payload["ok"] is False
    assert payload["reads_api_keys"] is False
    assert payload["safety"]["public_readonly"] is True
    assert payload["safety"]["real_orders"] is False
    assert payload["safety"]["signed_requests"] is False
    assert payload["safety"]["reads_api_keys"] is False
    assert payload["running"] is False
    assert payload["health"] == "not_running"
    assert payload["process_health"] == "not_running"
    assert payload["health_report_command"] == "bash scripts/start-auto-paper.sh health --json"
    assert payload["error"]["code"] == "paper_service_not_running"
    assert payload["mode"] == "paper"
    assert payload["state_path"].endswith("service_state.json")
    assert payload["ledger_path"].endswith("paper_ledger.json")
    assert payload["archive_path"].endswith("cycles.jsonl")
    assert payload["journal_path"].endswith("paper_audit.sqlite3")
    assert payload["cycle_timeout_seconds"] == 6000.0
    assert payload["paper_margin_budget_usdt"] is None
    assert payload["agent_margin_usdt"] is None
    assert payload["notional_usdt"] is None
    assert payload["paper_leverage"] is None
    assert payload["agent_trade_thesis_path"] == ""
    assert payload["agent_trade_thesis_configured"] is False
    assert payload["paper_autonomy_profile_path"] == str(tmp_path / "run" / "paper_autonomy_profile.json")
    assert payload["paper_autonomy_profile_configured"] is True
    assert payload["paper_autonomy_enabled"] is True
    assert payload["paper_autonomy_profile_defaulted"] is True
    assert payload["effective_notional_usdt"] == 10.0
    assert payload["agent_sizing_required"] is False
    assert payload["paper_sizing"]["source"] == "paper_autonomy_profile"
    assert payload["paper_sizing"]["requested_margin_usdt"] == 10.0
    assert payload["paper_sizing"]["paper_leverage"] == 1.0
    assert payload["paper_fee_bps"] == 4.0
    assert payload["paper_fee_model"] == "binance_usdm_public_docs_vip0_taker_fallback"
    assert payload["paper_slippage_bps"] == 0.0
    assert payload["paper_max_holding_minutes"] == 0.0
    assert "Agent" in payload["paper_max_holding_minutes_semantics"]
    assert payload["strategy_review_enabled"] is True
    assert payload["strategy_state_path"] == str(tmp_path / "run" / "strategy_state.json")
    assert payload["strategy_state_configured"] is True
    assert payload["strategy_review_report_path"] == str(tmp_path / "run" / "strategy-review-latest.json")
    assert payload["systemd_lifecycle_owner"] == "service"
    assert str(tmp_path / "run") in payload["runtime_dir"]


def test_auto_paper_service_status_can_disable_default_runtime_autonomy_profile(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "run"
    runtime_dir.mkdir()
    profile_path = runtime_dir / "paper_autonomy_profile.json"
    profile_path.write_text("{}", encoding="utf-8")
    env = {"TRADECAT_AUTO_PAPER_RUNTIME_DIR": str(runtime_dir), "TRADECAT_AUTO_PAPER_AUTONOMY_ENABLED": "0"}

    proc = run_service_script(["status", "--json"], env=env)

    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["paper_autonomy_profile_path"] == ""
    assert payload["paper_autonomy_profile_configured"] is False
    assert payload["agent_sizing_required"] is True
    assert payload["paper_autonomy_enabled"] is False
    assert payload["paper_autonomy_profile_defaulted"] is False


def test_auto_paper_service_status_treats_agent_thesis_path_as_autonomous_sizing_source(tmp_path: Path) -> None:
    env = {
        "TRADECAT_AUTO_PAPER_RUNTIME_DIR": str(tmp_path / "run"),
        "TRADECAT_AUTO_PAPER_AGENT_TRADE_THESIS_PATH": str(tmp_path / "agent-thesis.json"),
    }

    proc = run_service_script(["status", "--json"], env=env)

    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["agent_trade_thesis_path"] == str(tmp_path / "agent-thesis.json")
    assert payload["agent_trade_thesis_configured"] is True
    assert payload["paper_autonomy_profile_configured"] is False
    assert payload["agent_sizing_required"] is False
    assert payload["paper_sizing"]["source"] == "agent_trade_thesis"


def test_auto_paper_ops_check_reports_long_running_dependency_chain(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "run"
    env = {"TRADECAT_AUTO_PAPER_RUNTIME_DIR": str(runtime_dir)}

    proc = run_service_script(["ops-check", "--json"], env=env)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    checks = {item["id"]: item for item in payload["checks"]}
    assert payload["schema"] == "tradecat_auto.paper_ops_report.v1"
    assert payload["schema_version"] == "1.0.0"
    assert payload["ok"] is True
    assert payload["blocking_checks"] == []
    assert "tradecat-public repository-root Python project" in payload["dependency_chain"]
    assert "embedded Skill package at skills/tradecat-public" in payload["dependency_chain"]
    assert "auto-paper run-loop" in payload["dependency_chain"]
    assert payload["runtime"]["ledger_path"] == str(runtime_dir / "paper_ledger.json")
    assert payload["systemd"]["start_limit_burst"] == 5
    assert payload["systemd"]["lifecycle_owner"] == "service"
    assert payload["systemd"]["legacy_timer_policy"] == "disabled_on_install"
    assert payload["systemd"]["limit_nofile"] == 4096
    assert checks["no_binance_credential_env_names"]["ok"] is True
    assert checks["identity_detected"]["run_as_root"] in {True, False}
    assert payload["operations"]["health"].startswith("health-report detects")
    assert payload["safety"]["public_readonly"] is True
    assert payload["safety"]["real_orders"] is False
    assert payload["safety"]["signed_requests"] is False
    assert payload["safety"]["reads_api_keys"] is False


def test_auto_paper_web_monitor_is_local_readonly_entrypoint() -> None:
    proc = subprocess.run(
        [sys.executable, str(WEB_MONITOR_SCRIPT), "--help"],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "--host" in proc.stdout
    assert "--port" in proc.stdout

    source = (PROJECT_ROOT / WEB_MONITOR_SCRIPT).read_text(encoding="utf-8")
    assert 'default="127.0.0.1"' in source
    assert "def do_GET" in source
    assert "def do_POST" not in source
    assert "dependency_health" in source
    assert "仓库根 Python 项目环境" in source
    assert "risk_state" in source
    assert "decision_text" in source
    assert "latest_cycle" in source
    assert "source_http_status" in source
    assert "thesis_path" in source
    assert "process_health" in source
    assert "进程健康" in source
    assert "monitor_command_elapsed_ms" in source
    assert "监控命令耗时" in source
    assert "依赖链健康" in source
    assert "回撤/告警" in source
    assert "AI 文本决策" in source
    assert "def _monitor_report_flags" in source
    assert '"public_readonly": True' in source
    assert '"real_orders": False' in source
    assert '"signed_requests": False' in source
    assert '"reads_api_keys": False' in source


def test_auto_paper_web_monitor_report_flags_derive_from_safety_boundary() -> None:
    monitor = load_web_monitor_module()
    safety = monitor._monitor_safety_boundary()

    assert monitor._monitor_report_flags() == {
        "real_orders": safety["real_orders"],
        "signed_requests": safety["signed_requests"],
        "reads_api_keys": safety["reads_api_keys"],
    }


def test_auto_paper_web_monitor_run_json_records_command_elapsed_ms(tmp_path: Path) -> None:
    monitor = load_web_monitor_module()

    payload = monitor.run_json(
        [sys.executable, "-c", "import json; print(json.dumps({'ok': True}))"],
        runtime_dir=tmp_path,
    )

    assert payload["ok"] is True
    assert payload["_monitor_returncode"] == 0
    assert isinstance(payload["_monitor_elapsed_ms"], float | int)
    assert payload["_monitor_elapsed_ms"] >= 0


def test_auto_paper_web_monitor_summarizes_command_elapsed_ms() -> None:
    monitor = load_web_monitor_module()

    elapsed = monitor.monitor_command_elapsed_ms(
        {
            "status": {"_monitor_elapsed_ms": "1.5"},
            "health": {"_monitor_elapsed_ms": 2},
            "missing": {},
        }
    )

    assert elapsed == {"status": 1.5, "health": 2.0}


def test_auto_paper_web_monitor_does_not_warn_on_absent_optional_local_constraints() -> None:
    monitor = load_web_monitor_module()
    checks = [
        {"id": "python_available", "ok": True},
        {"id": "project_source_exists", "ok": True},
        {"id": "runtime_parent_exists", "ok": True},
        {"id": "runtime_parent_writable", "ok": True},
        {"id": "state_path_under_runtime", "ok": True},
        {"id": "ledger_path_under_runtime", "ok": True},
        {"id": "archive_path_under_runtime", "ok": True},
        {"id": "journal_path_under_runtime", "ok": True},
        {"id": "log_file_under_runtime", "ok": True},
        {"id": "pid_file_under_runtime", "ok": True},
        {"id": "no_binance_credential_env_names", "ok": True},
    ]

    nodes = monitor.build_dependency_health(
        status={
            "running": True,
            "process_health": "running_pid_verified",
            "agent_sizing_required": True,
            "agent_trade_thesis_path": "",
            "paper_autonomy_profile_path": "",
            "portfolio_risk_policy_path": "",
            "paper_kill_switch_path": "",
            "safety": {
                "real_orders": False,
                "signed_requests": False,
                "reads_api_keys": False,
                "binance_account_state": False,
            },
        },
        health={
            "ok": False,
            "status": "degraded",
            "alerts": ["last_error_present"],
            "heartbeat": {"ok": True, "stale": False},
            "service_state": {"cycles_attempted": 3},
            "archive": {"ok": True, "cycle_count": 3, "last_action": "PROCESSED"},
            "ledger": {"ok": True},
            "audit_journal": {"ok": True, "chain_valid": True},
        },
        ops={"ok": True, "checks": checks},
        audit={"ok": True, "chain_valid": True},
        latest_cycle={"input_change": {"trigger_reason": "new_signal_event"}, "events": {"ok": True, "events": []}},
        strategy_state={},
    )
    by_id = {item["id"]: item for item in nodes}

    assert "process_health=running_pid_verified" in by_id["operator_supervisor"]["detail"]
    assert by_id["context_audit"]["status"] == "ok"
    assert by_id["risk_controls"]["status"] == "ok"
    assert "默认不启用本地组合约束" in by_id["risk_controls"]["detail"]
    assert "not_configured" not in by_id["risk_controls"]["detail"]
    assert by_id["trade_thesis"]["status"] == "warn"
    assert "默认 runtime paper autonomy profile" in by_id["trade_thesis"]["detail"]
    assert by_id["strategy_iteration"]["status"] == "warn"


def test_auto_paper_web_monitor_snapshot_commands_are_bounded_and_complete(tmp_path: Path, monkeypatch) -> None:
    monitor = load_web_monitor_module()
    calls: list[tuple[str, ...]] = []

    def fake_run_json(command: list[str], *, runtime_dir: Path, timeout_seconds: float = 10.0) -> dict[str, object]:
        del runtime_dir, timeout_seconds
        calls.append(tuple(command))
        return {"ok": True, "command": command}

    monkeypatch.setattr(monitor, "run_json", fake_run_json)

    results = monitor.run_snapshot_commands(
        tmp_path,
        ledger_path=tmp_path / "paper_ledger.json",
        journal_path=tmp_path / "paper_audit.sqlite3",
    )

    assert set(results) == {"status", "health", "ops", "paper", "audit"}
    assert ("bash", "scripts/start-auto-paper.sh", "status", "--json") in calls
    assert ("bash", "scripts/start-auto-paper.sh", "health", "--json") in calls
    assert ("bash", "scripts/start-auto-paper.sh", "ops-check", "--json") in calls
    assert any(command[:4] == ("bash", "scripts/run-tradecat.sh", "auto", "paper-report") for command in calls)
    paper_command = next(
        command for command in calls if command[:4] == ("bash", "scripts/run-tradecat.sh", "auto", "paper-report")
    )
    assert "--detail-limit" in paper_command
    assert paper_command[paper_command.index("--detail-limit") + 1] == "5"
    assert any(command[:4] == ("bash", "scripts/run-tradecat.sh", "auto", "audit-journal") for command in calls)


def test_auto_paper_web_monitor_compacts_heavy_cycle_payloads() -> None:
    monitor = load_web_monitor_module()

    compact = monitor.compact_cycle_for_monitor(
        {
            "schema": "tradecat_auto.service_cycle.v1",
            "schema_version": "1.0.0",
            "ok": True,
            "action": "PROCESSED",
            "events": {
                "ok": True,
                "events": [
                    {"event_id": f"event-{index}", "symbol": "IRYSUSDT", "content": "signal"} for index in range(12)
                ],
            },
            "pipeline_report": {
                "schema": "tradecat_auto.run_once_report.v1",
                "schema_version": "1.0.0",
                "selected_symbol": "IRYSUSDT",
                "paper_ledger": {
                    "ok": True,
                    "open_positions": {"IRYSUSDT": {"marker": "THIS_SHOULD_NOT_LEAK"}},
                    "closed_positions": [{"marker": "THIS_SHOULD_NOT_LEAK"}],
                },
                "universe": [{"marker": "THIS_SHOULD_NOT_LEAK"}],
                "raw_errors": [{"marker": "THIS_SHOULD_NOT_LEAK"}],
                "risk_decision": {"decision": "ALLOW", "reasons": []},
                "paper_execution": {"status": "OPENED", "paper_execution_id": "paper-1"},
                "safety": {
                    "public_readonly": True,
                    "real_orders": False,
                    "signed_requests": False,
                    "reads_api_keys": False,
                },
            },
            "safety": {
                "public_readonly": True,
                "real_orders": False,
                "signed_requests": False,
                "reads_api_keys": False,
            },
        }
    )

    encoded = json.dumps(compact, ensure_ascii=False)
    assert compact["payload_compacted"] is True
    assert compact["events"]["events_count"] == 12
    assert compact["events"]["events_truncated"] is True
    assert len(compact["events"]["sample_events"]) == 10
    assert compact["pipeline_report"]["payload_compacted"] is True
    assert compact["pipeline_report"]["selected_symbol"] == "IRYSUSDT"
    assert compact["pipeline_report"]["raw_error_count"] == 1
    assert "THIS_SHOULD_NOT_LEAK" not in encoded
    assert "universe" not in compact["pipeline_report"]


def test_auto_paper_web_monitor_compacts_heavy_paper_report_payloads() -> None:
    monitor = load_web_monitor_module()

    compact = monitor.compact_paper_report_for_monitor(
        {
            "schema": "tradecat_auto.paper_report.v1",
            "schema_version": "1.0.0",
            "ok": True,
            "summary": {"equity_usdt": 1000.0, "open_positions_count": 1},
            "paper_account_state": {
                "summary": {"equity_usdt": 1000.0},
                "open_positions": {"IRYSUSDT": {"marker": "THIS_SHOULD_NOT_LEAK"}},
            },
            "open_positions": {"IRYSUSDT": {"marker": "THIS_SHOULD_NOT_LEAK"}},
            "closed_positions": [{"marker": "THIS_SHOULD_NOT_LEAK"}],
            "recent_paper_orders": [{"marker": "THIS_SHOULD_NOT_LEAK"}],
            "recent_fills": [{"marker": "THIS_SHOULD_NOT_LEAK"}],
            "equity_curve_tail": [{"marker": "THIS_SHOULD_NOT_LEAK"}],
            "safety": {
                "public_readonly": True,
                "real_orders": False,
                "signed_requests": False,
                "reads_api_keys": False,
            },
        }
    )

    encoded = json.dumps(compact, ensure_ascii=False)
    assert compact["payload_compacted"] is True
    assert compact["summary"]["equity_usdt"] == 1000.0
    assert compact["open_positions_count"] == 1
    assert compact["closed_positions_sample_count"] == 1
    assert compact["recent_paper_orders_count"] == 1
    assert compact["recent_fills_count"] == 1
    assert compact["paper_account_state"]["payload_compacted"] is True
    assert "THIS_SHOULD_NOT_LEAK" not in encoded


def test_auto_paper_web_monitor_snapshot_returns_compacted_runtime_payloads(tmp_path: Path, monkeypatch) -> None:
    monitor = load_web_monitor_module()
    raw_cycle = {
        "schema": "tradecat_auto.service_cycle.v1",
        "schema_version": "1.0.0",
        "ok": True,
        "action": "PROCESSED",
        "events": {"ok": True, "events": [{"event_id": "event-1", "symbol": "IRYSUSDT"}]},
        "latest_event": {
            "event_id": "event-1",
            "source_dataset_key": "signal_flow",
            "source_time_bj": "2026-05-18 08:00:00",
            "symbol": "IRYSUSDT",
            "content": "IRYSUSDT 信号流: 成交额暴增",
        },
        "pipeline_report": {
            "schema": "tradecat_auto.run_once_report.v1",
            "schema_version": "1.0.0",
            "selected_symbol": "IRYSUSDT",
            "agent_trade_thesis": {
                "schema": "tradecat_auto.agent_trade_thesis.v1",
                "schema_version": "1.0.0",
                "symbol": "IRYSUSDT",
                "direction": "LONG",
                "confidence": 0.7,
                "rationale": "Agent full raw rationale remains available to decision_text.",
            },
            "signal": {"symbol": "IRYSUSDT", "direction": "LONG", "score": 70, "tradable_candidate": True},
            "strategy_intent": {"action": "ENTER", "direction": "LONG"},
            "risk_decision": {"decision": "ALLOW", "reasons": [], "paper_leverage": 1},
            "paper_execution": {"status": "OPENED", "paper_execution_id": "paper-1"},
            "paper_ledger": {
                "ok": True,
                "open_positions": {"IRYSUSDT": {"marker": "THIS_SHOULD_NOT_LEAK"}},
            },
            "safety": {
                "public_readonly": True,
                "real_orders": False,
                "signed_requests": False,
                "reads_api_keys": False,
            },
        },
        "safety": {
            "public_readonly": True,
            "real_orders": False,
            "signed_requests": False,
            "reads_api_keys": False,
        },
    }

    def fake_read_json_file(path: Path) -> dict[str, object]:
        if path.name == "strategy_state.json":
            return {"enabled": True, "policy": {}, "status": "active"}
        return {
            "schema": "tradecat_auto.strategy_review.v1",
            "schema_version": "1.0.0",
            "ok": True,
            "metrics": {
                "overall": {"trades": 1, "net_pnl_usdt": 0.1},
                "by_symbol": {"IRYSUSDT": {"marker": "THIS_SHOULD_NOT_LEAK"}},
            },
            "recommendations": [{"symbol": "IRYSUSDT"}],
            "strategy_state": {"enabled": True},
            "safety": {
                "public_readonly": True,
                "real_orders": False,
                "signed_requests": False,
                "reads_api_keys": False,
            },
        }

    monkeypatch.setattr(monitor, "read_latest_cycle_pair", lambda path: (raw_cycle, raw_cycle))
    monkeypatch.setattr(monitor, "read_json_file", fake_read_json_file)
    monkeypatch.setattr(monitor, "read_tail", lambda path: [])
    monkeypatch.setattr(monitor, "credential_env_names", lambda: [])
    monkeypatch.setattr(
        monitor,
        "run_snapshot_commands",
        lambda runtime_dir, *, ledger_path, journal_path: {
            "status": {
                "ok": True,
                "running": True,
                "process_health": "running_pid_verified",
                "strategy_review_enabled": True,
                "safety": {
                    "real_orders": False,
                    "signed_requests": False,
                    "reads_api_keys": False,
                    "binance_account_state": False,
                },
            },
            "health": {
                "ok": True,
                "heartbeat": {"ok": True, "stale": False},
                "service_state": {"cycles_attempted": 1},
                "archive": {"ok": True, "cycle_count": 1},
                "ledger": {"ok": True, "summary": {"equity_usdt": 1000.0, "initial_balance_usdt": 1000.0}},
                "audit_journal": {"ok": True, "chain_valid": True},
                "alerts": [],
            },
            "ops": {"ok": True, "checks": []},
            "paper": {
                "schema": "tradecat_auto.paper_report.v1",
                "schema_version": "1.0.0",
                "ok": True,
                "summary": {"equity_usdt": 1000.0, "open_positions_count": 1},
                "paper_account_state": {"open_positions": {"IRYSUSDT": {"marker": "THIS_SHOULD_NOT_LEAK"}}},
                "open_positions": {"IRYSUSDT": {"marker": "THIS_SHOULD_NOT_LEAK"}},
            },
            "audit": {"ok": True, "chain_valid": True},
        },
    )

    snapshot = monitor.build_snapshot(tmp_path)
    encoded = json.dumps(snapshot, ensure_ascii=False)

    assert snapshot["decision_text"]["ok"] is True
    assert "Agent full raw rationale remains available" in snapshot["decision_text"]["text"]
    assert snapshot["latest_cycle"]["payload_compacted"] is True
    assert snapshot["latest_decision_cycle"]["pipeline_report"]["payload_compacted"] is True
    assert snapshot["paper"]["payload_compacted"] is True
    assert snapshot["strategy_review"]["payload_compacted"] is True
    assert snapshot["strategy_review"]["metrics"]["by_symbol_count"] == 1
    assert "THIS_SHOULD_NOT_LEAK" not in encoded


def test_auto_paper_web_monitor_extracts_auditable_decision_text() -> None:
    monitor = load_web_monitor_module()
    decision = monitor.build_decision_text(
        {
            "schema": "tradecat_auto.service_cycle.v1",
            "generated_at": "2026-05-18T00:00:00Z",
            "latest_event": {
                "event_id": "event-1",
                "source_dataset_key": "event_stream",
                "source_time_bj": "2026-05-18 08:00:00",
                "content": "这是一条新闻，不应作为输入信号 <script>",
            },
            "pipeline_report": {
                "schema": "tradecat_auto.run_once_report.v1",
                "selected_symbol": "IRYSUSDT",
                "enrichment": {
                    "schema": "tradecat_auto.market_enrichment.v1",
                    "symbol": "IRYSUSDT",
                    "raw_symbol": "IRYS",
                    "source_values": {
                        "交易对": "IRYS",
                        "5m量变化率": "-1.84%",
                        "5m额变化率": "3.40%",
                    },
                },
                "safety": {
                    "public_readonly_market_data": True,
                    "paper_or_watch_only": True,
                    "real_orders": False,
                    "signed_requests": False,
                    "reads_api_keys": False,
                    "binance_account_state": False,
                },
                "agent_trade_thesis": {
                    "schema": "tradecat_auto.agent_trade_thesis.v1",
                    "schema_version": "1.0.0",
                    "symbol": "IRYSUSDT",
                    "direction": "LONG",
                    "confidence": 0.72,
                    "rationale": "Agent sees public-market momentum with controlled paper risk.",
                    "risk_notes": ["Fixture only; not investment advice."],
                    "limitations": ["paper/watch only; no real order"],
                    "provenance": {"source": "fixture-agent"},
                },
                "signal": {
                    "symbol": "IRYSUSDT",
                    "direction": "LONG",
                    "score": 73,
                    "tradable_candidate": True,
                    "positive_factors": ["sheet_anomaly_present"],
                    "negative_factors": [],
                    "do_not_trade_reasons": [],
                    "metrics_used": {"quote_volume_24h": 50000000},
                },
                "strategy_intent": {
                    "action": "ENTER",
                    "entry_type": "MARKET_PAPER",
                    "entry_price": 0.062,
                    "invalidation_price": 0.055,
                    "take_profit_price": 0.08,
                    "max_holding_minutes": 45,
                    "exit_plan_source": "agent_trade_thesis",
                    "exit_rationale": "agent supplied invalidation and target",
                },
                "risk_decision": {
                    "decision": "ALLOW",
                    "reasons": [],
                    "paper_leverage": 2,
                    "constraints": ["paper_only"],
                    "policy": {"sizing_source": "agent_trade_thesis.paper_intent", "requested_margin_usdt": 7.5},
                },
                "paper_execution": {
                    "status": "OPENED",
                    "side": "LONG",
                    "notional_usdt": 15,
                    "margin_usdt": 7.5,
                    "quantity": 241.9,
                    "paper_execution_id": "exec-1",
                },
            },
        }
    )

    assert decision["schema"] == "tradecat_auto.paper_web_monitor_decision_text.v1"
    assert decision["ok"] is True
    assert decision["symbol"] == "IRYSUSDT"
    assert decision["decision"] == "ALLOW"
    assert decision["paper_execution_status"] == "OPENED"
    assert "Agent sees public-market momentum" in decision["text"]
    assert "IRYSUSDT 异动面板信号" in decision["text"]
    assert "5m量变化率=-1.84%" in decision["text"]
    assert "这是一条新闻" not in decision["text"]


def test_auto_paper_web_monitor_shows_full_signal_flow_input_fields() -> None:
    monitor = load_web_monitor_module()
    decision = monitor.build_decision_text(
        {
            "schema": "tradecat_auto.service_cycle.v1",
            "generated_at": "2026-05-18T00:00:00Z",
            "latest_event": {
                "event_id": "signal-1",
                "source_dataset_key": "signal_flow",
                "source_dataset_keys": ["signal_flow", "anomaly_panel"],
                "source_time_bj": "2026-05-18 17:40:48",
                "symbol": "FORMUSDT",
                "period": "5分钟",
                "signal_type": "成交额暴增",
                "content": "FORMUSDT 信号流: 周期=5分钟; 类型=成交额暴增; 内容=成交额暴增",
                "source_values": {
                    "时间(北京)": "2026-05-18 17:40:48",
                    "交易对": "FORM",
                    "周期": "5分钟",
                    "类型": "成交额暴增",
                    "内容": "成交额暴增；方向=提醒，强度=70",
                },
                "related_anomaly_panel": {
                    "row_index": 3,
                    "normalized_symbol": "FORMUSDT",
                    "source_values": {
                        "交易对": "FORM",
                        "5m量变化率": "0.909%",
                        "5m额变化率": "-3.657%",
                        "量额背离": "-4.565%",
                        "现持仓额": "5667814.63",
                    },
                },
            },
            "pipeline_report": {
                "schema": "tradecat_auto.run_once_report.v1",
                "selected_symbol": "FORMUSDT",
                "signal_flow_events": {
                    "count": 2,
                    "duplicate_count": 1,
                    "first_10": [
                        {
                            "source_dataset_key": "signal_flow",
                            "source_time_bj": "2026-05-18 17:40:48",
                            "symbol": "FORMUSDT",
                            "period": "5分钟",
                            "signal_type": "成交额暴增",
                            "content": "FORMUSDT 信号流: 成交额暴增",
                            "source_values": {"交易对": "FORM", "周期": "5分钟", "类型": "成交额暴增"},
                        },
                        {
                            "source_dataset_key": "signal_flow",
                            "source_time_bj": "2026-05-18 17:41:12",
                            "symbol": "FIDAUSDT",
                            "period": "15分钟",
                            "signal_type": "MACD金叉",
                            "content": "FIDAUSDT 信号流: MACD金叉",
                            "source_values": {"交易对": "FIDA", "周期": "15分钟", "类型": "MACD金叉"},
                        },
                    ],
                },
                "anomaly_symbols": {
                    "count": 2,
                    "first_10": [
                        {
                            "row_index": 8,
                            "raw_symbol": "FF",
                            "normalized_symbol": "FFUSDT",
                            "source_values": {
                                "交易对": "FF",
                                "5m量变化率": "-0.082%",
                                "5m额变化率": "4.866%",
                                "现持仓额": "35965182.49",
                            },
                        },
                        {
                            "row_index": 9,
                            "raw_symbol": "FIDA",
                            "normalized_symbol": "FIDAUSDT",
                            "source_values": {
                                "交易对": "FIDA",
                                "5m量变化率": "2.724%",
                                "5m额变化率": "4.388%",
                                "现持仓额": "9122768.65",
                            },
                        },
                    ],
                },
                "signal": {"symbol": "FORMUSDT", "direction": "LONG"},
                "risk_decision": {"decision": "REJECT", "reasons": ["agent_sizing_required"]},
                "paper_execution": {"status": "REJECTED"},
                "safety": {
                    "public_readonly_market_data": True,
                    "paper_or_watch_only": True,
                    "real_orders": False,
                    "signed_requests": False,
                    "reads_api_keys": False,
                    "binance_account_state": False,
                },
            },
        }
    )

    assert decision["ok"] is True
    input_section = next(item for item in decision["sections"] if item["title"] == "输入信号")
    assert "来源: signal_flow" in input_section["text"]
    assert "周期: 5分钟" in input_section["text"]
    assert "类型: 成交额暴增" in input_section["text"]
    assert "原始字段: 时间(北京)=2026-05-18 17:40:48" in input_section["text"]
    assert "关联异动面板: row=3; symbol=FORMUSDT" in input_section["text"]
    assert "现持仓额=5667814.63" in input_section["text"]
    candidates_section = next(item for item in decision["sections"] if item["title"] == "本轮输入候选")
    assert "信号流抓取数: 2" in candidates_section["text"]
    assert "信号流去重丢弃数: 1" in candidates_section["text"]
    assert "FIDAUSDT 信号流: MACD金叉" in candidates_section["text"]
    assert "异动面板抓取数: 2" in candidates_section["text"]
    assert "FFUSDT" in candidates_section["text"]
    assert "现持仓额=9122768.65" in candidates_section["text"]
    assert decision["safety"]["real_orders"] is False
    assert decision["safety"]["signed_requests"] is False
    assert decision["safety"]["reads_api_keys"] is False
    assert decision["safety"]["public_readonly"] is True


def test_auto_paper_web_monitor_does_not_trust_archived_safety_flags() -> None:
    monitor = load_web_monitor_module()
    unsafe_safety = {
        "public_readonly_market_data": False,
        "public_readonly": False,
        "paper_or_watch_only": False,
        "real_orders": True,
        "signed_requests": True,
        "reads_api_keys": True,
        "binance_account_state": True,
    }
    cycle = {
        "schema": "tradecat_auto.service_cycle.v1",
        "schema_version": "1.0.0",
        "ok": True,
        "action": "PROCESSED",
        "real_orders": True,
        "signed_requests": True,
        "reads_api_keys": True,
        "safety": unsafe_safety,
        "latest_event": {"event_id": "unsafe-safety", "symbol": "IRYSUSDT"},
        "pipeline_report": {
            "schema": "tradecat_auto.run_once_report.v1",
            "schema_version": "1.0.0",
            "ok": True,
            "selected_symbol": "IRYSUSDT",
            "real_orders": True,
            "signed_requests": True,
            "reads_api_keys": True,
            "safety": unsafe_safety,
            "risk_decision": {"decision": "ALLOW", "reasons": []},
            "paper_execution": {"status": "OPENED", "side": "LONG"},
        },
    }

    compact_cycle = monitor.compact_cycle_for_monitor(cycle)
    compact_pipeline = compact_cycle["pipeline_report"]
    decision = monitor.build_decision_text(cycle)
    strategy_review = monitor.compact_strategy_review_for_monitor({"ok": True, "safety": unsafe_safety})
    paper_report = monitor.compact_paper_report_for_monitor({"ok": True, "safety": unsafe_safety})

    for payload in (compact_cycle, compact_pipeline, decision, strategy_review, paper_report):
        assert payload["safety"]["public_readonly"] is True
        assert payload["safety"]["paper_or_watch_only"] is True
        assert payload["safety"]["real_orders"] is False
        assert payload["safety"]["signed_requests"] is False
        assert payload["safety"]["reads_api_keys"] is False
        assert payload["safety"]["binance_account_state"] is False
    assert compact_cycle["real_orders"] is False
    assert compact_cycle["signed_requests"] is False
    assert compact_cycle["reads_api_keys"] is False
    assert compact_pipeline["real_orders"] is False
    assert compact_pipeline["signed_requests"] is False
    assert compact_pipeline["reads_api_keys"] is False


def test_auto_paper_web_monitor_uses_latest_cycle_with_pipeline_for_decision_text(tmp_path: Path) -> None:
    monitor = load_web_monitor_module()
    archive_path = tmp_path / "cycles.jsonl"
    archive_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "schema": "tradecat_auto.service_cycle.v1",
                        "action": "PROCESSED",
                        "pipeline_report": {
                            "schema": "tradecat_auto.run_once_report.v1",
                            "selected_symbol": "IRYSUSDT",
                        },
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "schema": "tradecat_auto.service_cycle.v1",
                        "action": "SKIPPED_DUPLICATE_EVENT",
                        "latest_event": {
                            "schema": "tradecat_auto.anomaly_signal_event.v1",
                            "source_dataset_key": "anomaly_panel",
                            "symbol": "IRYSUSDT",
                        },
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    latest = monitor.read_latest_jsonl(archive_path)
    latest_decision = monitor.read_latest_decision_jsonl(archive_path)
    latest_pair, latest_decision_pair = monitor.read_latest_cycle_pair(archive_path)

    assert latest["action"] == "SKIPPED_DUPLICATE_EVENT"
    assert latest_decision["action"] == "PROCESSED"
    assert latest_decision["pipeline_report"]["selected_symbol"] == "IRYSUSDT"
    assert latest_pair["action"] == latest["action"]
    assert latest_decision_pair["pipeline_report"]["selected_symbol"] == "IRYSUSDT"


def test_auto_paper_web_monitor_reads_latest_jsonl_when_last_line_exceeds_initial_tail_window(tmp_path: Path) -> None:
    monitor = load_web_monitor_module()
    archive_path = tmp_path / "cycles.jsonl"
    archive_path.write_text(
        "\n".join(
            [
                json.dumps({"schema": "tradecat_auto.service_cycle.v1", "action": "OLD"}, ensure_ascii=False),
                json.dumps(
                    {
                        "schema": "tradecat_auto.service_cycle.v1",
                        "action": "PROCESSED",
                        "pipeline_report": {
                            "schema": "tradecat_auto.run_once_report.v1",
                            "selected_symbol": "BIGUSDT",
                            "large_text": "x" * 2048,
                        },
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    latest = monitor.read_latest_jsonl(archive_path, max_bytes=64)
    latest_decision = monitor.read_latest_decision_jsonl(archive_path, max_bytes=64)
    latest_pair, latest_decision_pair = monitor.read_latest_cycle_pair(archive_path, max_bytes=64)

    assert latest["action"] == "PROCESSED"
    assert latest_decision["pipeline_report"]["selected_symbol"] == "BIGUSDT"
    assert latest_pair["action"] == "PROCESSED"
    assert latest_decision_pair["pipeline_report"]["selected_symbol"] == "BIGUSDT"


def test_auto_paper_ops_check_rejects_binance_credential_env_names(tmp_path: Path) -> None:
    env = {
        "TRADECAT_AUTO_PAPER_RUNTIME_DIR": str(tmp_path / "run"),
        "BINANCE_API_KEY": "synthetic-placeholder",
    }

    proc = run_service_script(["ops-check", "--json"], env=env)

    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    checks = {item["id"]: item for item in payload["checks"]}
    assert payload["schema"] == "tradecat_auto.paper_ops_report.v1"
    assert payload["ok"] is False
    assert "no_binance_credential_env_names" in payload["blocking_checks"]
    assert checks["no_binance_credential_env_names"]["env_names"] == ["BINANCE_API_KEY"]
    assert payload["error"]["code"] == "paper_ops_preflight_failed"


def test_auto_paper_running_status_reads_effective_sizing_from_process_env(tmp_path: Path) -> None:
    fake_python = tmp_path / "fake-python"
    fake_python.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "if len(sys.argv) > 1 and sys.argv[1] == '-':\n"
        "    exec(sys.stdin.read())\n"
        "else:\n"
        "    print(json.dumps({'schema': 'fake.cycle', 'ok': True}))\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    runtime_dir = tmp_path / "run"
    start_env = {
        "PYTHON_BIN": str(fake_python),
        "TRADECAT_AUTO_PAPER_RUNTIME_DIR": str(runtime_dir),
        "TRADECAT_AUTO_PAPER_INTERVAL_SECONDS": "999",
        "TRADECAT_AUTO_PAPER_AGENT_MARGIN_USDT": "7.5",
        "TRADECAT_AUTO_PAPER_LEVERAGE": "3",
        "TRADECAT_AUTO_PAPER_AGENT_TRADE_THESIS_PATH": str(tmp_path / "agent-thesis.json"),
        "TRADECAT_AUTO_PAPER_AUTONOMY_PROFILE_PATH": str(tmp_path / "paper-autonomy.json"),
    }
    status_env = {"TRADECAT_AUTO_PAPER_RUNTIME_DIR": str(runtime_dir)}

    start_proc = run_service_script(["start", "--json"], env=start_env)
    try:
        assert start_proc.returncode == 0, start_proc.stderr
        status_proc = run_service_script(["status", "--json"], env=status_env)
        assert status_proc.returncode == 0, status_proc.stderr
        payload = json.loads(status_proc.stdout)
        assert payload["running"] is True
        assert payload["health"] == "running_pid_verified"
        assert payload["process_health"] == "running_pid_verified"
        assert payload["health_report_command"] == "bash scripts/start-auto-paper.sh health --json"
        if hasattr(os, "getsid"):
            assert os.getsid(payload["pid"]) != os.getsid(0)
        assert payload["agent_margin_usdt"] == 7.5
        assert payload["paper_margin_budget_usdt"] is None
        assert payload["paper_leverage"] == 3.0
        assert payload["agent_trade_thesis_path"] == str(tmp_path / "agent-thesis.json")
        assert payload["agent_trade_thesis_configured"] is True
        assert payload["paper_autonomy_profile_path"] == str(tmp_path / "paper-autonomy.json")
        assert payload["paper_autonomy_profile_configured"] is True
        assert payload["effective_notional_usdt"] == 22.5
        assert payload["agent_sizing_required"] is False
        assert payload["paper_sizing"]["source"] == "service_environment"
    finally:
        run_service_script(["stop", "--json"], env=status_env)


def test_auto_paper_heal_starts_when_process_is_missing(tmp_path: Path) -> None:
    fake_python = tmp_path / "fake-python"
    fake_python.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "if len(sys.argv) > 1 and sys.argv[1] == '-':\n"
        "    exec(sys.stdin.read())\n"
        "else:\n"
        "    print(json.dumps({'schema': 'fake.cycle', 'ok': True}))\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    runtime_dir = tmp_path / "run"
    env = {
        "PYTHON_BIN": str(fake_python),
        "TRADECAT_AUTO_PAPER_RUNTIME_DIR": str(runtime_dir),
        "TRADECAT_AUTO_PAPER_INTERVAL_SECONDS": "999",
    }

    proc = run_service_script(["heal", "--json"], env=env)
    try:
        assert proc.returncode == 0, proc.stderr
        payload = json.loads(proc.stdout)
        assert payload["schema"] == "tradecat_auto.paper_service_status.v1"
        assert payload["action"] == "heal"
        assert payload["running"] is True
        assert payload["health"] == "spawned_unverified"
        assert payload["process_health"] == "spawned_unverified"
        assert payload["safety"]["real_orders"] is False
    finally:
        run_service_script(["stop", "--json"], env={"TRADECAT_AUTO_PAPER_RUNTIME_DIR": str(runtime_dir)})


def test_auto_paper_systemd_install_writes_long_running_user_service_and_disables_legacy_timer(
    tmp_path: Path,
) -> None:
    fake_systemctl, systemctl_log = make_fake_systemctl(tmp_path)
    systemd_dir = tmp_path / "systemd-user"
    runtime_dir = tmp_path / "run"
    env = {
        "TRADECAT_AUTO_PAPER_RUNTIME_DIR": str(runtime_dir),
        "TRADECAT_AUTO_PAPER_SYSTEMD_USER_DIR": str(systemd_dir),
        "TRADECAT_AUTO_PAPER_SYSTEMCTL_BIN": str(fake_systemctl),
        "FAKE_SYSTEMCTL_LOG": str(systemctl_log),
        "TRADECAT_AUTO_PAPER_INTERVAL_SECONDS": "17",
        "HTTPS_PROXY": "http://127.0.0.1:7890",
        "NO_PROXY": "localhost,127.0.0.1,::1",
    }

    proc = run_service_script(["systemd-install", "--json"], env=env)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["schema"] == "tradecat_auto.paper_service_status.v1"
    assert payload["ok"] is True
    assert payload["action"] == "systemd-install"
    assert payload["state"] == "enabled"
    assert payload["running"] is True
    assert payload["systemd_user_dir"] == str(systemd_dir)
    assert payload["systemd_timer_unit"] == "tradecat-auto-paper.timer"
    assert payload["systemd_service_unit"] == "tradecat-auto-paper.service"
    assert payload["systemd_lifecycle_owner"] == "service"

    service_path = systemd_dir / "tradecat-auto-paper.service"
    timer_path = systemd_dir / "tradecat-auto-paper.timer"
    service_text = service_path.read_text(encoding="utf-8")
    assert service_path.exists()
    assert not timer_path.exists()
    assert "Type=simple" in service_text
    assert f"WorkingDirectory={PROJECT_ROOT}" in service_text
    assert f"ExecStart={PROJECT_ROOT}/scripts/start-auto-paper.sh _run" in service_text
    assert f"Environment=TRADECAT_AUTO_PAPER_RUNTIME_DIR={runtime_dir}" in service_text
    assert "Environment=HTTPS_PROXY=http://127.0.0.1:7890" in service_text
    assert "Environment=NO_PROXY=localhost,127.0.0.1,::1" in service_text
    assert "Environment=TRADECAT_AUTO_PAPER_MARGIN_BUDGET_USDT=" not in service_text
    assert "Environment=TRADECAT_AUTO_PAPER_AGENT_MARGIN_USDT=" not in service_text
    assert "Environment=TRADECAT_AUTO_PAPER_EFFECTIVE_NOTIONAL_USDT=" not in service_text
    assert "Environment=TRADECAT_AUTO_PAPER_LEVERAGE=" not in service_text
    assert "Environment=TRADECAT_AUTO_PAPER_AGENT_TRADE_THESIS_PATH=" not in service_text
    assert (
        f"Environment=TRADECAT_AUTO_PAPER_AUTONOMY_PROFILE_PATH={runtime_dir / 'paper_autonomy_profile.json'}"
        in service_text
    )
    assert "Environment=TRADECAT_AUTO_PAPER_AUTONOMY_ENABLED=1" in service_text
    assert "Environment=TRADECAT_AUTO_PAPER_AUTONOMY_MARGIN_USDT=10" in service_text
    assert "Environment=TRADECAT_AUTO_PAPER_AUTONOMY_LEVERAGE=1" in service_text
    assert "Environment=TRADECAT_AUTO_PAPER_AUTONOMY_DIRECTION_POLICY=sheet_signal_or_taker_flow" in service_text
    assert "Environment=TRADECAT_AUTO_PAPER_CYCLE_TIMEOUT_SECONDS=6000" in service_text
    assert "Environment=TRADECAT_AUTO_PAPER_MAX_EVENT_AGE_SECONDS=" not in service_text
    assert "Environment=TRADECAT_AUTO_PAPER_FEE_BPS=4" in service_text
    assert "Environment=TRADECAT_AUTO_PAPER_SLIPPAGE_BPS=0" in service_text
    assert "Environment=TRADECAT_AUTO_PAPER_MAX_HOLDING_MINUTES=0" in service_text
    assert "Environment=TRADECAT_AUTO_PAPER_STRATEGY_REVIEW_ENABLED=1" in service_text
    assert f"Environment=TRADECAT_AUTO_PAPER_STRATEGY_STATE_PATH={runtime_dir / 'strategy_state.json'}" in service_text
    assert (
        f"Environment=TRADECAT_AUTO_PAPER_STRATEGY_REVIEW_REPORT_PATH={runtime_dir / 'strategy-review-latest.json'}"
        in service_text
    )
    assert "Environment=TRADECAT_AUTO_PAPER_STRATEGY_REVIEW_MIN_CLOSED_POSITIONS=50" in service_text
    assert "Environment=TRADECAT_AUTO_PAPER_STRATEGY_REVIEW_MAX_OPEN_POSITIONS=50" in service_text
    assert "Environment=TRADECAT_AUTO_PAPER_STRATEGY_REVIEW_MAX_POSITIONS_PER_SYMBOL=3" in service_text
    assert "Environment=TRADECAT_AUTO_PAPER_NOTIONAL_USDT=" not in service_text
    assert f"Environment=TRADECAT_AUTO_PAPER_JOURNAL_PATH={runtime_dir / 'paper_audit.sqlite3'}" in service_text
    assert "StartLimitIntervalSec=600" in service_text
    assert "StartLimitBurst=5" in service_text
    assert "Restart=on-failure" in service_text
    assert "RestartSec=30s" in service_text
    assert "TimeoutStartSec=120" in service_text
    assert "TimeoutStopSec=30" in service_text
    assert "StandardOutput=append:" in service_text
    assert "StandardError=append:" in service_text
    assert "UMask=0077" in service_text
    assert "LimitNOFILE=4096" in service_text
    assert "TasksMax=64" in service_text
    assert "NoNewPrivileges=true" in service_text
    assert "PrivateDevices=true" in service_text
    assert "LockPersonality=true" in service_text
    assert "RestrictSUIDSGID=true" in service_text
    assert systemctl_log.read_text(encoding="utf-8").splitlines() == [
        "--user disable --now tradecat-auto-paper.timer",
        "--user stop tradecat-auto-paper.service",
        "--user daemon-reload",
        "--user reset-failed tradecat-auto-paper.service",
        "--user enable --now tradecat-auto-paper.service",
        "--user is-active --quiet tradecat-auto-paper.service",
    ]


def test_auto_paper_cycle_omits_margin_budget_arg_when_unset(tmp_path: Path) -> None:
    argv_path = tmp_path / "argv.json"
    fake_python = tmp_path / "fake-python"
    fake_python.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "open(os.environ['ARGV_PATH'], 'w', encoding='utf-8').write(json.dumps(sys.argv))\n"
        "print(json.dumps({'schema': 'fake.cycle', 'ok': True}))\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    env = {
        "PYTHON_BIN": str(fake_python),
        "ARGV_PATH": str(argv_path),
        "TRADECAT_AUTO_PAPER_RUNTIME_DIR": str(tmp_path / "run"),
        "TRADECAT_AUTO_PAPER_AGENT_MARGIN_USDT": "7.5",
        "TRADECAT_AUTO_PAPER_LEVERAGE": "3",
        "TRADECAT_AUTO_PAPER_AGENT_TRADE_THESIS_PATH": str(tmp_path / "agent-thesis.json"),
        "TRADECAT_AUTO_PAPER_AUTONOMY_PROFILE_PATH": str(tmp_path / "paper-autonomy.json"),
    }

    proc = run_service_script(["_cycle"], env=env)

    assert proc.returncode == 0, proc.stderr
    argv = json.loads(argv_path.read_text(encoding="utf-8"))
    assert "--agent-margin-usdt" in argv
    assert "--paper-leverage" in argv
    assert "--agent-trade-thesis-path" in argv
    assert str(tmp_path / "agent-thesis.json") in argv
    assert "--paper-autonomy-profile-path" in argv
    assert str(tmp_path / "paper-autonomy.json") in argv
    assert "--strategy-state-path" in argv
    assert "--paper-margin-budget-usdt" not in argv
    assert "--event-limit" in argv
    assert argv[argv.index("--event-limit") + 1] == "0"
    assert "--max-event-age-seconds" not in argv


def test_auto_paper_cycle_refreshes_default_runtime_autonomy_profile(tmp_path: Path) -> None:
    argv_path = tmp_path / "argv.json"
    fake_python = tmp_path / "fake-python"
    fake_python.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "if len(sys.argv) > 1 and sys.argv[1] == '-':\n"
        "    exec(sys.stdin.read())\n"
        "else:\n"
        "    open(os.environ['ARGV_PATH'], 'w', encoding='utf-8').write(json.dumps(sys.argv))\n"
        "    print(json.dumps({'schema': 'fake.cycle', 'ok': True}))\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    runtime_dir = tmp_path / "run"
    runtime_dir.mkdir()
    profile_path = runtime_dir / "paper_autonomy_profile.json"
    profile_path.write_text(
        json.dumps(
            {
                "schema": "tradecat_auto.paper_autonomy_profile.v1",
                "schema_version": "1.0.0",
                "paper_intent": {"direction_policy": "price_momentum_on_conflict"},
                "provenance": {"source": "local_operator_runtime_profile"},
            }
        ),
        encoding="utf-8",
    )
    env = {
        "PYTHON_BIN": str(fake_python),
        "ARGV_PATH": str(argv_path),
        "TRADECAT_AUTO_PAPER_RUNTIME_DIR": str(runtime_dir),
    }

    proc = run_service_script(["_cycle"], env=env)

    assert proc.returncode == 0, proc.stderr
    refreshed = json.loads(profile_path.read_text(encoding="utf-8"))
    assert refreshed["provenance"]["source"] == "scripts/start-auto-paper.sh"
    assert refreshed["safety"]["public_readonly"] is True
    assert refreshed["paper_intent"]["direction_policy"] == "sheet_signal_or_taker_flow"
    assert refreshed["paper_intent"]["allow_signal_reject_override"] is True
    argv = json.loads(argv_path.read_text(encoding="utf-8"))
    assert "--paper-autonomy-profile-path" in argv
    assert argv[argv.index("--paper-autonomy-profile-path") + 1] == str(profile_path)
    assert "--strategy-state-path" in argv


def test_auto_paper_systemd_uninstall_removes_user_units(tmp_path: Path) -> None:
    fake_systemctl, systemctl_log = make_fake_systemctl(tmp_path)
    systemd_dir = tmp_path / "systemd-user"
    systemd_dir.mkdir(parents=True)
    (systemd_dir / "tradecat-auto-paper.service").write_text("old service", encoding="utf-8")
    (systemd_dir / "tradecat-auto-paper.timer").write_text("old timer", encoding="utf-8")
    env = {
        "TRADECAT_AUTO_PAPER_RUNTIME_DIR": str(tmp_path / "run"),
        "TRADECAT_AUTO_PAPER_SYSTEMD_USER_DIR": str(systemd_dir),
        "TRADECAT_AUTO_PAPER_SYSTEMCTL_BIN": str(fake_systemctl),
        "FAKE_SYSTEMCTL_LOG": str(systemctl_log),
    }

    proc = run_service_script(["systemd-uninstall", "--json"], env=env)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["action"] == "systemd-uninstall"
    assert payload["state"] == "disabled"
    assert not (systemd_dir / "tradecat-auto-paper.service").exists()
    assert not (systemd_dir / "tradecat-auto-paper.timer").exists()
    assert systemctl_log.read_text(encoding="utf-8").splitlines() == [
        "--user disable --now tradecat-auto-paper.service",
        "--user disable --now tradecat-auto-paper.timer",
        "--user daemon-reload",
    ]


def test_auto_paper_script_exposes_self_contained_health_daily_and_alert_entrypoints(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "run"
    runtime_dir.mkdir(parents=True)
    (runtime_dir / "service_state.json").write_text(
        json.dumps({"schema": "tradecat_auto.service_state.v1", "last_attempt_at": "2026-05-15T00:00:00Z"}),
        encoding="utf-8",
    )
    (runtime_dir / "paper_ledger.json").write_text(
        json.dumps(
            {
                "schema": "tradecat_auto.paper_ledger.v1",
                "cash_balance_usdt": 1000.0,
                "equity_usdt": 1000.0,
                "initial_balance_usdt": 1000.0,
                "realized_pnl_usdt": 0.0,
                "unrealized_pnl_usdt": 0.0,
                "open_positions": {},
                "closed_positions": [],
                "paper_orders": [],
                "fills": [],
                "applied_execution_ids": [],
                "ignored_execution_ids": [],
                "equity_curve": [],
            }
        ),
        encoding="utf-8",
    )
    (runtime_dir / "cycles.jsonl").write_text(
        '{"schema":"tradecat_auto.service_cycle.v1","action":"PROCESSED","ok":true}\n', encoding="utf-8"
    )
    append_audit_record(
        runtime_dir / "paper_audit.sqlite3",
        event_type="service_cycle",
        payload={"schema": "tradecat_auto.service_cycle.v1", "ok": True},
        run_id="script-health",
        idempotency_key="service_cycle:script-health",
    )
    env = {
        "TRADECAT_AUTO_PAPER_RUNTIME_DIR": str(runtime_dir),
        "TRADECAT_AUTO_PAPER_MAX_HEARTBEAT_AGE_SECONDS": "999999999",
    }

    health_proc = run_service_script(["health", "--json"], env=env)
    assert health_proc.returncode == 0, health_proc.stderr
    health = json.loads(health_proc.stdout)
    assert health["schema"] == "tradecat_auto.production_health.v1"
    assert health["ledger"]["path"] == str(runtime_dir / "paper_ledger.json")

    daily_proc = run_service_script(["daily", "--json"], env=env)
    assert daily_proc.returncode == 0, daily_proc.stderr
    daily = json.loads(daily_proc.stdout)
    assert daily["schema"] == "tradecat_auto.daily_paper_report.v1"
    assert daily["cycle_counts"]["PROCESSED"] == 1

    alert_proc = run_service_script(["alert", "--json"], env=env)
    assert alert_proc.returncode == 0, alert_proc.stderr
    alert = json.loads(alert_proc.stdout)
    assert alert["schema"] == "tradecat_auto.telegram_alerts.v1"
    assert alert["alerts"][0]["real_orders"] is False


def test_auto_paper_json_flag_is_only_passed_when_requested(tmp_path: Path) -> None:
    fake_python = tmp_path / "fake-python"
    argv_log = tmp_path / "argv.json"
    fake_python.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "Path(os.environ['ARGV_LOG']).write_text(json.dumps(sys.argv), encoding='utf-8')\n"
        "print(json.dumps({'schema': 'fake', 'ok': True}))\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    env = {
        "PYTHON_BIN": str(fake_python),
        "ARGV_LOG": str(argv_log),
        "TRADECAT_AUTO_PAPER_RUNTIME_DIR": str(tmp_path / "run"),
    }

    plain_proc = run_service_script(["health"], env=env)
    assert plain_proc.returncode == 0, plain_proc.stderr
    assert "--json" not in json.loads(argv_log.read_text(encoding="utf-8"))

    json_proc = run_service_script(["health", "--json"], env=env)
    assert json_proc.returncode == 0, json_proc.stderr
    assert "--json" in json.loads(argv_log.read_text(encoding="utf-8"))
