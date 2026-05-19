from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from tradecat_auto.safety_boundary import paper_watch_safety_boundary

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "validate_testing_ci_contract.py"


def load_validator_module():
    spec = importlib.util.spec_from_file_location("validate_testing_ci_contract", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("validate_testing_ci_contract.py could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestingCiContractTests(unittest.TestCase):
    def test_testing_ci_contract_expected_safety_uses_canonical_boundary(self) -> None:
        validator = load_validator_module()

        self.assertEqual(validator.EXPECTED_SAFETY, paper_watch_safety_boundary())

    def test_testing_ci_contract_passes_for_current_repository(self) -> None:
        validator = load_validator_module()

        errors = validator.validate(PROJECT_ROOT)

        self.assertEqual(errors, [])

    def test_testing_ci_contract_fails_when_required_ci_step_is_missing(self) -> None:
        validator = load_validator_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "resources").mkdir()
            (root / ".github" / "workflows").mkdir(parents=True)
            (root / "scripts").mkdir()
            (root / "tests").mkdir()
            (root / "contracts").mkdir()
            (root / "tests" / "test_placeholder.py").write_text("def test_placeholder():\n    assert True\n")
            (root / "contracts" / "placeholder.json").write_text("{}\n", encoding="utf-8")
            matrix = {
                "schema": "tradecat_public.test_ci_matrix.v1",
                "schema_version": "1.0.0",
                "provenance": {"source": "test"},
                "safety": {
                    "public_readonly_market_data": True,
                    "public_readonly": True,
                    "paper_or_watch_only": True,
                    "real_orders": False,
                    "signed_requests": False,
                    "reads_api_keys": False,
                    "binance_account_state": False,
                },
                "test_layers": [
                    {
                        "id": "placeholder",
                        "description": "placeholder",
                        "evidence_globs": ["tests/test_placeholder.py", "contracts/*.json"],
                    }
                ],
                "ci_contract": {
                    "workflow_path": ".github/workflows/ci.yml",
                    "required_triggers": ["push"],
                    "required_top_level_snippets": ["permissions:", "cancel-in-progress: true"],
                    "required_jobs": ["verify"],
                    "required_job_snippets": {"verify": ["timeout-minutes: 30"]},
                    "required_step_names": ["Testing/CI contract"],
                    "required_command_snippets": ["python scripts/validate_testing_ci_contract.py"],
                    "required_wheel_package_paths": ["tradecat_auto/safety_boundary.py"],
                },
                "local_gate_contract": {
                    "script_path": "scripts/verify-project.sh",
                    "required_command_snippets": ["scripts/validate_testing_ci_contract.py"],
                },
                "makefile_contract": {
                    "path": "Makefile",
                    "required_targets": ["test-ci-contract"],
                    "required_command_snippets": ["python scripts/validate_testing_ci_contract.py"],
                },
            }
            (root / "resources" / "test_ci_matrix.json").write_text(
                json.dumps(matrix, ensure_ascii=False),
                encoding="utf-8",
            )
            (root / ".github" / "workflows" / "ci.yml").write_text(
                "name: CI\non:\n  push:\njobs:\n  verify:\n    steps: []\n",
                encoding="utf-8",
            )
            (root / "scripts" / "verify-project.sh").write_text(
                "python scripts/validate_testing_ci_contract.py\n",
                encoding="utf-8",
            )
            (root / "Makefile").write_text("test:\n\tpython -m pytest\n", encoding="utf-8")

            errors = validator.validate(root)

        self.assertIn("ci_step_missing: Testing/CI contract", errors)
        self.assertIn("ci_command_missing: python scripts/validate_testing_ci_contract.py", errors)
        self.assertIn("ci_top_level_missing: permissions:", errors)
        self.assertIn("ci_top_level_missing: cancel-in-progress: true", errors)
        self.assertIn("ci_job_contract_missing:verify: timeout-minutes: 30", errors)
        self.assertIn("ci_wheel_package_path_missing: tradecat_auto/safety_boundary.py", errors)
        self.assertTrue(
            any(error.startswith("wheel_source_path_missing: tradecat_auto/safety_boundary.py") for error in errors)
        )
        self.assertIn("makefile_target_missing: test-ci-contract", errors)
        self.assertIn("makefile_command_missing: python scripts/validate_testing_ci_contract.py", errors)

    def test_testing_ci_contract_requires_non_empty_wheel_package_paths(self) -> None:
        validator = load_validator_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "resources").mkdir()
            (root / ".github" / "workflows").mkdir(parents=True)
            (root / "scripts").mkdir()
            (root / "tests").mkdir()
            (root / "tests" / "test_placeholder.py").write_text("def test_placeholder():\n    assert True\n")
            matrix = {
                "schema": "tradecat_public.test_ci_matrix.v1",
                "schema_version": "1.0.0",
                "provenance": {"source": "test"},
                "safety": {
                    "public_readonly_market_data": True,
                    "public_readonly": True,
                    "paper_or_watch_only": True,
                    "real_orders": False,
                    "signed_requests": False,
                    "reads_api_keys": False,
                    "binance_account_state": False,
                },
                "test_layers": [
                    {
                        "id": "placeholder",
                        "description": "placeholder",
                        "evidence_globs": ["tests/test_placeholder.py"],
                    }
                ],
                "ci_contract": {
                    "workflow_path": ".github/workflows/ci.yml",
                    "required_triggers": ["push"],
                    "required_top_level_snippets": [],
                    "required_jobs": ["verify"],
                    "required_job_snippets": {},
                    "required_step_names": [],
                    "required_command_snippets": [],
                },
                "local_gate_contract": {"script_path": "scripts/verify-project.sh", "required_command_snippets": []},
                "makefile_contract": {"path": "Makefile", "required_targets": [], "required_command_snippets": []},
            }
            (root / "resources" / "test_ci_matrix.json").write_text(json.dumps(matrix), encoding="utf-8")
            (root / ".github" / "workflows" / "ci.yml").write_text(
                "name: CI\non:\n  push:\njobs:\n  verify:\n    steps: []\n",
                encoding="utf-8",
            )
            (root / "scripts" / "verify-project.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            (root / "Makefile").write_text("test:\n\tpython -m pytest\n", encoding="utf-8")

            errors = validator.validate(root)

        self.assertIn("missing_required_wheel_package_paths", errors)


if __name__ == "__main__":
    unittest.main()
