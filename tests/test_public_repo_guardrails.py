from __future__ import annotations

import ast
import json
import re
import subprocess
from pathlib import Path

from tradecat_auto.agent_market_context import FORBIDDEN_ENDPOINTS
from tradecat_auto.safety_boundary import paper_watch_safety_boundary

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_PACKAGE_ROOT = REPO_ROOT / "skills" / "tradecat-public"

ACTIVE_CODE_PREFIXES = (
    ".github/workflows/",
    "scripts/",
    "src/",
    "skills/tradecat-public/agents/",
    "skills/tradecat-public/scripts/",
)
ACTIVE_CODE_SUFFIXES = (".py", ".sh", ".yaml", ".yml")

ALLOWLISTED_POLICY_FILES = {
    "src/tradecat_auto/agent_market_context.py",
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
CANONICAL_PAPER_WATCH_FLAG_KEYS = (
    "real_orders",
    "signed_requests",
    "reads_api_keys",
    "binance_account_state",
)
CANONICAL_PAPER_WATCH_FLAG_OWNER = "src/tradecat_auto/safety_boundary.py"


def _active_code_files() -> list[Path]:
    output = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "--cached", "--others", "--exclude-standard"],
        check=True,
        text=True,
        capture_output=True,
    ).stdout.splitlines()
    paths: set[Path] = set()
    for raw_path in output:
        if not raw_path.endswith(ACTIVE_CODE_SUFFIXES):
            continue
        if not raw_path.startswith(ACTIVE_CODE_PREFIXES):
            continue
        paths.add(Path(raw_path))
    return sorted(paths)


def _read_repo_text(relative_path: Path) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_private_binance_endpoint_literals_only_live_in_denylist_policy():
    assert DISALLOWED_BINANCE_PRIVATE_ENDPOINTS <= FORBIDDEN_ENDPOINTS

    findings: list[str] = []
    for relative_path in _active_code_files():
        if relative_path.as_posix() in ALLOWLISTED_POLICY_FILES:
            continue
        text = _read_repo_text(relative_path)
        for endpoint in sorted(DISALLOWED_BINANCE_PRIVATE_ENDPOINTS):
            if endpoint in text:
                findings.append(f"{relative_path}: private endpoint literal {endpoint}")

    assert findings == []


def test_active_code_has_no_binance_credentials_or_mutating_http_calls():
    findings: list[str] = []
    for relative_path in _active_code_files():
        text = _read_repo_text(relative_path)
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


def test_active_code_guard_scans_untracked_worktree_files():
    assert Path("src/tradecat_auto/safety_boundary.py") in _active_code_files()


def test_core_python_code_uses_canonical_paper_watch_flag_helpers():
    findings: list[str] = []
    for relative_path in _active_code_files():
        path_text = relative_path.as_posix()
        if (
            not path_text.startswith("src/")
            or not path_text.endswith(".py")
            or path_text == CANONICAL_PAPER_WATCH_FLAG_OWNER
        ):
            continue
        text = _read_repo_text(relative_path)
        tree = ast.parse(text, filename=path_text)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            for key, value in zip(node.keys, node.values, strict=False):
                if (
                    isinstance(key, ast.Constant)
                    and key.value in CANONICAL_PAPER_WATCH_FLAG_KEYS
                    and isinstance(value, ast.Constant)
                    and value.value is False
                ):
                    findings.append(f"{relative_path}:{node.lineno}: hand-written {key.value}=False")

    assert findings == []


def test_manifest_keeps_security_and_supply_chain_gates_declared():
    payload = json.loads((SKILL_PACKAGE_ROOT / "agents" / "manifest.json").read_text(encoding="utf-8"))
    validation_commands = {item["command"]: item for item in payload["validation_commands"]}

    assert validation_commands["bash scripts/security-scan.sh"]["risk_class"] == "security_or_supply_chain"
    assert validation_commands["bash scripts/supply-chain-audit.sh"]["risk_class"] == "security_or_supply_chain"
    assert (
        validation_commands["python3 scripts/validate_dependency_policy.py"]["risk_class"] == "security_or_supply_chain"
    )
    assert validation_commands["ruff format --check src tests scripts"]["risk_class"] == "local_readonly"
    assert payload["important_paths"]["private_executor_boundary_reference"] == (
        "skills/tradecat-public/references/private-executor-boundary.md"
    )
    assert payload["important_paths"]["audited_intent_handoff_schema"] == (
        "contracts/tradecat-auto-audited-intent-handoff.schema.json"
    )


def test_manifest_never_advertises_real_order_capability():
    payload = json.loads((SKILL_PACKAGE_ROOT / "agents" / "manifest.json").read_text(encoding="utf-8"))
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


def test_large_project_governance_entrypoints_exist():
    required_paths = [
        "CONTRIBUTING.md",
        "CHANGELOG.md",
        "LICENSE",
        ".editorconfig",
        ".env.example",
        ".github/pull_request_template.md",
        ".github/CODEOWNERS",
        ".github/dependabot.yml",
        "docs/ARCHITECTURE.md",
        "docs/configuration.md",
        "docs/deployment.md",
        "docs/release.md",
        "scripts/validate_dependency_policy.py",
    ]

    missing = [path for path in required_paths if not (REPO_ROOT / path).is_file()]

    assert missing == []


def test_ci_enforces_repository_governance_gates():
    ci_text = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    verify_text = (REPO_ROOT / "scripts" / "verify-project.sh").read_text(encoding="utf-8")

    required_snippets = [
        "python scripts/validate_dependency_policy.py",
        "ruff format --check src tests scripts",
        "bash scripts/guard_public_local_files.sh",
        "bash scripts/supply-chain-audit.sh",
    ]

    findings = []
    for snippet in required_snippets:
        if snippet not in ci_text and snippet not in verify_text:
            findings.append(snippet)

    assert findings == []


def test_agent_smoke_trade_thesis_fixture_uses_canonical_safety_boundary():
    smoke_text = (REPO_ROOT / "scripts" / "agent-smoke.sh").read_text(encoding="utf-8")
    thesis_start = smoke_text.index('"agent_trade_thesis"')
    market_data_start = smoke_text.index('"market_data"', thesis_start)
    thesis_block = smoke_text[thesis_start:market_data_start]

    for key, expected_value in paper_watch_safety_boundary().items():
        expected_literal = "True" if expected_value is True else "False"
        assert f'"{key}": {expected_literal}' in thesis_block
