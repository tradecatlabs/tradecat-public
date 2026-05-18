from __future__ import annotations

from pathlib import Path

import tradecat_auto
from tradecat_terminal import cli as terminal_cli


def test_tradecat_auto_package_is_served_from_tradecat_public_project() -> None:
    package_path = Path(tradecat_auto.__file__).resolve()
    project_root = Path(__file__).resolve().parents[1]

    assert package_path.is_relative_to(project_root / "src" / "tradecat_auto")


def test_tradecat_cli_routes_auto_subcommands(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_auto_main(argv: list[str] | None = None) -> int:
        calls.append(list(argv or []))
        return 7

    import tradecat_auto.cli as auto_cli

    monkeypatch.setattr(auto_cli, "main", fake_auto_main)

    exit_code = terminal_cli.main(["auto", "paper-report", "--json"])

    assert exit_code == 7
    assert calls == [["paper-report", "--json"]]
