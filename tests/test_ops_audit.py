from __future__ import annotations

import importlib.util
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "ops-audit.py"


def load_ops_audit_module():
    spec = importlib.util.spec_from_file_location("ops_audit", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("ops-audit.py could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_executable(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


def test_ops_audit_reports_clean_manual_mode(tmp_path: Path, monkeypatch) -> None:
    module = load_ops_audit_module()
    start_script = tmp_path / "start-auto-paper.sh"
    systemctl = tmp_path / "systemctl"
    ps_fixture = tmp_path / "ps.txt"
    ss_fixture = tmp_path / "ss.txt"
    cron_fixture = tmp_path / "cron.txt"
    tmux_fixture = tmp_path / "tmux.txt"
    systemd_dir = tmp_path / "systemd-user"
    systemd_dir.mkdir()
    runtime_dir = tmp_path / "runtime"
    status = {
        "schema": "tradecat_auto.paper_service_status.v1",
        "schema_version": "1.0.0",
        "state": "not_running",
        "running": False,
        "runtime_dir": str(runtime_dir),
        "paper_autonomy_profile_path": "",
        "paper_autonomy_profile_configured": False,
        "paper_autonomy_profile_defaulted": False,
        "paper_autonomy_enabled": False,
        "paper_sizing": {"source": "missing"},
    }
    write_executable(start_script, f"#!/usr/bin/env bash\nprintf '%s\\n' '{json.dumps(status)}'\nexit 1\n")
    write_executable(
        systemctl,
        "#!/usr/bin/env bash\n"
        'if [ "$2" = "is-active" ]; then echo inactive; exit 3; fi\n'
        'if [ "$2" = "is-enabled" ]; then echo not-found; exit 1; fi\n'
        "exit 0\n",
    )
    ps_fixture.write_text("1 0 S init\n", encoding="utf-8")
    ss_fixture.write_text("", encoding="utf-8")
    cron_fixture.write_text("", encoding="utf-8")
    tmux_fixture.write_text("0:2.1 bash /home/lenovo/.projects/cat/tradecat-public\n", encoding="utf-8")
    monkeypatch.setenv("TRADECAT_OPS_AUDIT_START_SCRIPT", str(start_script))
    monkeypatch.setenv("TRADECAT_OPS_AUDIT_SYSTEMCTL_BIN", str(systemctl))
    monkeypatch.setenv("TRADECAT_OPS_AUDIT_SYSTEMD_USER_DIR", str(systemd_dir))
    monkeypatch.setenv("TRADECAT_OPS_AUDIT_PS_FIXTURE", str(ps_fixture))
    monkeypatch.setenv("TRADECAT_OPS_AUDIT_SS_FIXTURE", str(ss_fixture))
    monkeypatch.setenv("TRADECAT_OPS_AUDIT_CRON_FIXTURE", str(cron_fixture))
    monkeypatch.setenv("TRADECAT_OPS_AUDIT_TMUX_FIXTURE", str(tmux_fixture))

    report = module.build_report(tmp_path)

    assert report["schema"] == "tradecat_public.ops_audit.v1"
    assert report["ok"] is True
    assert report["manual_mode"] is True
    assert report["issues"] == []
    assert report["systemd"]["residue_paths"] == []
    assert report["runtime"]["paper_autonomy_profile_configured"] is False
    assert report["runtime"]["paper_sizing_source"] == "missing"
    assert report["runtime"]["runtime_owner"] == "none"
    assert report["runtime"]["configured_lifecycle_owner"] == "manual"
    assert report["tmux"] == []
    assert report["safety"]["real_orders"] is False
    assert "does not prove local auto-paper is running" in report["ci_runtime_note"]


def test_ops_audit_flags_service_residue_and_runtime_process(tmp_path: Path, monkeypatch) -> None:
    module = load_ops_audit_module()
    start_script = tmp_path / "start-auto-paper.sh"
    systemctl = tmp_path / "systemctl"
    ps_fixture = tmp_path / "ps.txt"
    ss_fixture = tmp_path / "ss.txt"
    cron_fixture = tmp_path / "cron.txt"
    tmux_fixture = tmp_path / "tmux.txt"
    systemd_dir = tmp_path / "systemd-user"
    systemd_dir.mkdir()
    (systemd_dir / "tradecat-daemon.service").write_text("[Service]\n", encoding="utf-8")
    status = {
        "schema": "tradecat_auto.paper_service_status.v1",
        "schema_version": "1.0.0",
        "state": "not_running",
        "running": False,
        "runtime_dir": str(tmp_path / "runtime"),
        "paper_autonomy_profile_path": "",
        "paper_autonomy_profile_configured": False,
        "paper_autonomy_profile_defaulted": False,
        "paper_autonomy_enabled": False,
        "paper_sizing": {"source": "missing"},
    }
    write_executable(start_script, f"#!/usr/bin/env bash\nprintf '%s\\n' '{json.dumps(status)}'\nexit 1\n")
    write_executable(
        systemctl,
        "#!/usr/bin/env bash\n"
        'if [ "$2" = "is-active" ]; then echo inactive; exit 3; fi\n'
        'if [ "$2" = "is-enabled" ]; then echo disabled; exit 1; fi\n'
        "exit 0\n",
    )
    ps_fixture.write_text(
        "123 1 S bash /repo/tradecat-public/scripts/start-auto-paper.sh _run\n",
        encoding="utf-8",
    )
    ss_fixture.write_text("LISTEN 0 1 127.0.0.1:8765 0.0.0.0:* users:(('python',pid=7,fd=3))\n", encoding="utf-8")
    cron_fixture.write_text("* * * * * bash scripts/start-auto-paper.sh _cycle\n", encoding="utf-8")
    tmux_fixture.write_text(
        "0:3.1 bash /home/lenovo/.projects/cat/tradecat-public/scripts/start-auto-paper.sh\n", encoding="utf-8"
    )
    monkeypatch.setenv("TRADECAT_OPS_AUDIT_START_SCRIPT", str(start_script))
    monkeypatch.setenv("TRADECAT_OPS_AUDIT_SYSTEMCTL_BIN", str(systemctl))
    monkeypatch.setenv("TRADECAT_OPS_AUDIT_SYSTEMD_USER_DIR", str(systemd_dir))
    monkeypatch.setenv("TRADECAT_OPS_AUDIT_PS_FIXTURE", str(ps_fixture))
    monkeypatch.setenv("TRADECAT_OPS_AUDIT_SS_FIXTURE", str(ss_fixture))
    monkeypatch.setenv("TRADECAT_OPS_AUDIT_CRON_FIXTURE", str(cron_fixture))
    monkeypatch.setenv("TRADECAT_OPS_AUDIT_TMUX_FIXTURE", str(tmux_fixture))

    report = module.build_report(tmp_path)

    assert report["ok"] is False
    assert "runtime_process_residue" in report["issues"]
    assert "cron_residue" in report["warnings"]
    assert "tmux_runtime_pane_residue" in report["warnings"]
    assert report["tmux"]
    assert any(path.endswith("tradecat-daemon.service") for path in report["systemd"]["residue_paths"])
    assert "monitor_or_tradecat_port_listening" in report["warnings"]
