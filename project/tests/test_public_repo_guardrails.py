from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from tradecat_auto.agent_market_context import FORBIDDEN_ENDPOINTS

SKILL_ROOT = Path(__file__).resolve().parents[2]

ACTIVE_CODE_PREFIXES = (
    ".github/workflows/",
    "project/scripts/",
    "project/src/",
    "scripts/",
)
ACTIVE_CODE_SUFFIXES = (".py", ".sh", ".yaml", ".yml")

ALLOWLISTED_POLICY_FILES = {
    "project/src/tradecat_auto/agent_market_context.py",
}

DISALLOWED_BINANCE_PRIVATE_ENDPOINTS = {
    "/api/v3/order",
    "/fapi/v1/batchOrders",
    "/fapi/v1/leverage",
    "/fapi/v1/listenKey",
    "/fapi/v1/marginType",
    "/fapi/v1/order",
    "/fapi/v1/order/test",
    "/fapi/v2/account",
    "/fapi/v2/balance",
    "/fapi/v2/positionRisk",
    "/sapi/",
}

MUTATING_HTTP_CALL = re.compile(r"\b(?:requests|httpx)\.(?:post|put|patch|delete)\s*\(")
URLLIB_MUTATING_REQUEST = re.compile(
    r"\burllib\.request\.Request\s*\([^)]*\bmethod\s*=\s*['\"](?:POST|PUT|PATCH|DELETE)['\"]",
    re.DOTALL,
)
BINANCE_CREDENTIAL_ENV_READ = re.compile(
    r"(?:os\.environ(?:\.get)?|os\.getenv)\(\s*['\"]BINANCE_[A-Z0-9_]*(?:KEY|SECRET|API)['\"]"
)
SHELL_BINANCE_CREDENTIAL_REFERENCE = re.compile(r"\$\{?BINANCE_[A-Z0-9_]*(?:KEY|SECRET|API)\b")
BINANCE_API_KEY_HEADER = re.compile(r"X-MBX-APIKEY", re.IGNORECASE)


def _tracked_active_code_files() -> list[Path]:
    output = subprocess.run(
        ["git", "-C", str(SKILL_ROOT), "ls-files"],
        check=True,
        text=True,
        capture_output=True,
    ).stdout.splitlines()
    paths: list[Path] = []
    for raw_path in output:
        if not raw_path.endswith(ACTIVE_CODE_SUFFIXES):
            continue
        if not raw_path.startswith(ACTIVE_CODE_PREFIXES):
            continue
        paths.append(Path(raw_path))
    return paths


def _read_tracked_text(relative_path: Path) -> str:
    return (SKILL_ROOT / relative_path).read_text(encoding="utf-8")


def test_private_binance_endpoint_literals_only_live_in_denylist_policy():
    assert DISALLOWED_BINANCE_PRIVATE_ENDPOINTS <= FORBIDDEN_ENDPOINTS

    findings: list[str] = []
    for relative_path in _tracked_active_code_files():
        if relative_path.as_posix() in ALLOWLISTED_POLICY_FILES:
            continue
        text = _read_tracked_text(relative_path)
        for endpoint in sorted(DISALLOWED_BINANCE_PRIVATE_ENDPOINTS):
            if endpoint in text:
                findings.append(f"{relative_path}: private endpoint literal {endpoint}")

    assert findings == []


def test_active_code_has_no_binance_credentials_or_mutating_http_calls():
    findings: list[str] = []
    for relative_path in _tracked_active_code_files():
        text = _read_tracked_text(relative_path)
        checks = {
            "binance credential env read": BINANCE_CREDENTIAL_ENV_READ,
            "shell binance credential reference": SHELL_BINANCE_CREDENTIAL_REFERENCE,
            "binance api-key header": BINANCE_API_KEY_HEADER,
            "mutating http call": MUTATING_HTTP_CALL,
            "urllib mutating request": URLLIB_MUTATING_REQUEST,
        }
        for label, pattern in checks.items():
            if pattern.search(text):
                findings.append(f"{relative_path}: {label}")

    assert findings == []


def test_manifest_keeps_security_and_supply_chain_gates_declared():
    payload = json.loads((SKILL_ROOT / "agents" / "manifest.json").read_text(encoding="utf-8"))
    validation_commands = {item["command"]: item for item in payload["validation_commands"]}

    assert validation_commands["bash scripts/security-scan.sh"]["risk_class"] == "security_or_supply_chain"
    assert validation_commands["bash scripts/supply-chain-audit.sh"]["risk_class"] == "security_or_supply_chain"
    assert payload["important_paths"]["private_executor_boundary_reference"] == "references/private-executor-boundary.md"
    assert payload["important_paths"]["audited_intent_handoff_schema"] == (
        "project/contracts/tradecat-auto-audited-intent-handoff.schema.json"
    )


def test_manifest_never_advertises_real_order_capability():
    payload = json.loads((SKILL_ROOT / "agents" / "manifest.json").read_text(encoding="utf-8"))
    findings: list[str] = []

    def walk(value: object, path: str) -> None:
        if isinstance(value, dict):
            for key in ("real_orders", "signed_requests", "reads_api_keys"):
                if value.get(key) is not None and value.get(key) is not False:
                    findings.append(f"{path}.{key}={value.get(key)!r}")
            for key, child in value.items():
                walk(child, f"{path}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{path}[{index}]")

    walk(payload, "manifest")

    assert findings == []
