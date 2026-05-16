from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from tradecat_auto.audit_journal import append_audit_record

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path("scripts/start-auto-paper.sh")


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
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$*\" >>\"$FAKE_SYSTEMCTL_LOG\"\n"
        "exit 0\n",
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
    assert payload["running"] is False
    assert payload["error"]["code"] == "paper_service_not_running"
    assert payload["mode"] == "paper"
    assert payload["state_path"].endswith("service_state.json")
    assert payload["ledger_path"].endswith("paper_ledger.json")
    assert payload["archive_path"].endswith("cycles.jsonl")
    assert payload["journal_path"].endswith("paper_audit.sqlite3")
    assert str(tmp_path / "run") in payload["runtime_dir"]


def test_auto_paper_systemd_install_writes_user_timer_and_service(tmp_path: Path) -> None:
    fake_systemctl, systemctl_log = make_fake_systemctl(tmp_path)
    systemd_dir = tmp_path / "systemd-user"
    runtime_dir = tmp_path / "run"
    env = {
        "TRADECAT_AUTO_PAPER_RUNTIME_DIR": str(runtime_dir),
        "TRADECAT_AUTO_PAPER_SYSTEMD_USER_DIR": str(systemd_dir),
        "TRADECAT_AUTO_PAPER_SYSTEMCTL_BIN": str(fake_systemctl),
        "FAKE_SYSTEMCTL_LOG": str(systemctl_log),
        "TRADECAT_AUTO_PAPER_INTERVAL_SECONDS": "17",
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

    service_path = systemd_dir / "tradecat-auto-paper.service"
    timer_path = systemd_dir / "tradecat-auto-paper.timer"
    service_text = service_path.read_text(encoding="utf-8")
    timer_text = timer_path.read_text(encoding="utf-8")
    assert service_path.exists()
    assert timer_path.exists()
    assert "Type=oneshot" in service_text
    assert f"WorkingDirectory={PROJECT_ROOT}" in service_text
    assert f"ExecStart={PROJECT_ROOT}/scripts/start-auto-paper.sh _cycle" in service_text
    assert f"Environment=TRADECAT_AUTO_PAPER_RUNTIME_DIR={runtime_dir}" in service_text
    assert f"Environment=TRADECAT_AUTO_PAPER_JOURNAL_PATH={runtime_dir / 'paper_audit.sqlite3'}" in service_text
    assert "NoNewPrivileges=true" in service_text
    assert "OnBootSec=30s" in timer_text
    assert "OnUnitActiveSec=17s" in timer_text
    assert "Unit=tradecat-auto-paper.service" in timer_text
    assert systemctl_log.read_text(encoding="utf-8").splitlines() == [
        "--user daemon-reload",
        "--user enable --now tradecat-auto-paper.timer",
    ]


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
    (runtime_dir / "cycles.jsonl").write_text('{"schema":"tradecat_auto.service_cycle.v1","action":"PROCESSED","ok":true}\n', encoding="utf-8")
    append_audit_record(
        runtime_dir / "paper_audit.sqlite3",
        event_type="service_cycle",
        payload={"schema": "tradecat_auto.service_cycle.v1", "ok": True},
        run_id="script-health",
        idempotency_key="service_cycle:script-health",
    )
    env = {"TRADECAT_AUTO_PAPER_RUNTIME_DIR": str(runtime_dir), "TRADECAT_AUTO_PAPER_MAX_HEARTBEAT_AGE_SECONDS": "999999999"}

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
