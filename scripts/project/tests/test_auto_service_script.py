from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

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
