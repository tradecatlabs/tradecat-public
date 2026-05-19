#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from tradecat_auto.safety_boundary import paper_watch_safety_boundary  # noqa: E402

SCHEMA = "tradecat_public.test_ci_matrix.v1"
SCHEMA_VERSION = "1.0.0"
DEFAULT_MATRIX_PATH = Path("resources/test_ci_matrix.json")
EXPECTED_SAFETY = paper_watch_safety_boundary()


def validate(root: Path) -> list[str]:
    matrix_path = root / DEFAULT_MATRIX_PATH
    errors: list[str] = []
    try:
        matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"test_ci_matrix_load_failed: {matrix_path}: {exc}"]
    if not isinstance(matrix, dict):
        return ["test_ci_matrix_invalid: root must be an object"]
    errors.extend(_validate_matrix_header(matrix))
    errors.extend(_validate_safety(matrix))
    errors.extend(_validate_test_layers(root, matrix))
    errors.extend(_validate_ci_contract(root, matrix))
    errors.extend(_validate_local_gate_contract(root, matrix))
    errors.extend(_validate_makefile_contract(root, matrix))
    return errors


def _validate_matrix_header(matrix: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if matrix.get("schema") != SCHEMA:
        errors.append(f"invalid_schema: expected {SCHEMA}")
    if matrix.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"invalid_schema_version: expected {SCHEMA_VERSION}")
    provenance = matrix.get("provenance")
    if not isinstance(provenance, dict) or not str(provenance.get("source") or "").strip():
        errors.append("missing_provenance_source")
    return errors


def _validate_safety(matrix: dict[str, Any]) -> list[str]:
    safety = matrix.get("safety") if isinstance(matrix.get("safety"), dict) else {}
    errors: list[str] = []
    for key, expected in EXPECTED_SAFETY.items():
        if safety.get(key) is not expected:
            errors.append(f"safety_boundary_violation: {key} must be {str(expected).lower()}")
    return errors


def _validate_test_layers(root: Path, matrix: dict[str, Any]) -> list[str]:
    layers = matrix.get("test_layers") if isinstance(matrix.get("test_layers"), list) else []
    errors: list[str] = []
    if not layers:
        return ["missing_test_layers"]
    seen: set[str] = set()
    for index, layer in enumerate(layers):
        if not isinstance(layer, dict):
            errors.append(f"invalid_test_layer[{index}]: layer must be an object")
            continue
        layer_id = str(layer.get("id") or "").strip()
        if not layer_id:
            errors.append(f"invalid_test_layer[{index}]: id is required")
        elif layer_id in seen:
            errors.append(f"duplicate_test_layer: {layer_id}")
        seen.add(layer_id)
        globs = layer.get("evidence_globs") if isinstance(layer.get("evidence_globs"), list) else []
        if not globs:
            errors.append(f"test_layer_missing_evidence: {layer_id or index}")
            continue
        for pattern in globs:
            if not _glob_matches(root, str(pattern)):
                errors.append(f"test_layer_evidence_missing: {layer_id}:{pattern}")
    return errors


def _validate_ci_contract(root: Path, matrix: dict[str, Any]) -> list[str]:
    contract = matrix.get("ci_contract") if isinstance(matrix.get("ci_contract"), dict) else {}
    workflow_path = root / str(contract.get("workflow_path") or "")
    errors: list[str] = []
    try:
        text = workflow_path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"ci_workflow_load_failed: {workflow_path}: {exc}"]
    for trigger in _string_list(contract.get("required_triggers")):
        if not re.search(rf"^\s*{re.escape(trigger)}\s*:", text, flags=re.MULTILINE):
            errors.append(f"ci_trigger_missing: {trigger}")
    errors.extend(
        _require_snippets(text, _string_list(contract.get("required_top_level_snippets")), "ci_top_level_missing")
    )
    for job in _string_list(contract.get("required_jobs")):
        if not re.search(rf"^\s{{2}}{re.escape(job)}\s*:", text, flags=re.MULTILINE):
            errors.append(f"ci_job_missing: {job}")
    required_job_snippets = contract.get("required_job_snippets")
    if isinstance(required_job_snippets, dict):
        for job, snippets in required_job_snippets.items():
            job_text = _ci_job_block(text, str(job))
            if not job_text:
                continue
            errors.extend(_require_snippets(job_text, _string_list(snippets), f"ci_job_contract_missing:{job}"))
    for step_name in _string_list(contract.get("required_step_names")):
        if not re.search(rf"^\s*-\s+name:\s+{re.escape(step_name)}\s*$", text, flags=re.MULTILINE):
            errors.append(f"ci_step_missing: {step_name}")
    errors.extend(
        _require_snippets(text, _string_list(contract.get("required_command_snippets")), "ci_command_missing")
    )
    wheel_package_paths = _string_list(contract.get("required_wheel_package_paths"))
    if not wheel_package_paths:
        errors.append("missing_required_wheel_package_paths")
    for package_path in wheel_package_paths:
        if package_path not in text:
            errors.append(f"ci_wheel_package_path_missing: {package_path}")
        source_path = _wheel_source_path(root, package_path)
        if not source_path.exists():
            errors.append(f"wheel_source_path_missing: {package_path} -> {source_path.relative_to(root)}")
    return errors


def _validate_local_gate_contract(root: Path, matrix: dict[str, Any]) -> list[str]:
    contract = matrix.get("local_gate_contract") if isinstance(matrix.get("local_gate_contract"), dict) else {}
    script_path = root / str(contract.get("script_path") or "")
    try:
        text = script_path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"local_gate_load_failed: {script_path}: {exc}"]
    return _require_snippets(
        text,
        _string_list(contract.get("required_command_snippets")),
        "local_gate_command_missing",
    )


def _validate_makefile_contract(root: Path, matrix: dict[str, Any]) -> list[str]:
    contract = matrix.get("makefile_contract") if isinstance(matrix.get("makefile_contract"), dict) else {}
    if not contract:
        return ["missing_makefile_contract"]
    path = root / str(contract.get("path") or "Makefile")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"makefile_load_failed: {path}: {exc}"]
    errors: list[str] = []
    for target in _string_list(contract.get("required_targets")):
        if not re.search(rf"^{re.escape(target)}\s*:", text, flags=re.MULTILINE):
            errors.append(f"makefile_target_missing: {target}")
    errors.extend(
        _require_snippets(text, _string_list(contract.get("required_command_snippets")), "makefile_command_missing")
    )
    return errors


def _require_snippets(text: str, snippets: list[str], code: str) -> list[str]:
    errors: list[str] = []
    for snippet in snippets:
        if snippet not in text:
            errors.append(f"{code}: {snippet}")
    return errors


def _ci_job_block(text: str, job: str) -> str:
    match = re.search(rf"^\s{{2}}{re.escape(job)}\s*:\n", text, flags=re.MULTILINE)
    if not match:
        return ""
    start = match.start()
    next_match = re.search(r"^\s{2}[A-Za-z0-9_-]+\s*:\n", text[match.end() :], flags=re.MULTILINE)
    if next_match is None:
        return text[start:]
    return text[start : match.end() + next_match.start()]


def _glob_matches(root: Path, pattern: str) -> bool:
    return any(path.exists() for path in root.glob(pattern))


def _wheel_source_path(root: Path, package_path: str) -> Path:
    if package_path.startswith(("tradecat_auto/", "tradecat_sources/")):
        return root / "src" / package_path
    return root / package_path


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate TradeCat testing and CI/CD contract.")
    parser.add_argument("--root", default=".", help="Repository root. Defaults to current directory.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable validation result.")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    errors = validate(root)
    payload = {
        "schema": "tradecat_public.test_ci_contract_validation.v1",
        "schema_version": SCHEMA_VERSION,
        "ok": not errors,
        "root": str(root),
        "errors": errors,
        "safety": EXPECTED_SAFETY,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    elif errors:
        for error in errors:
            print(error, file=sys.stderr)
    else:
        print("testing/ci contract ok")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
