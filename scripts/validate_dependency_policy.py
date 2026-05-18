#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"

APPROVED_DIRECT_DEPENDENCIES = {
    "urllib3": "runtime public HTTP client",
    "jsonschema": "dev schema validation",
    "pytest": "dev tests",
    "ruff": "dev lint and formatting",
    "jinja2": "optional report rendering",
    "pandas": "optional report data frames",
    "plotly": "optional report charts",
    "optuna": "optional research optimization",
    "quantstats": "optional research analytics",
    "vectorbt": "optional research backtesting",
}

APPROVED_BUILD_DEPENDENCIES = {
    "hatchling": "PEP 517 build backend",
}


def normalize_requirement_name(requirement: str) -> str:
    raw = requirement.strip()
    match = re.match(r"([A-Za-z0-9_.-]+)", raw)
    if not match:
        raise ValueError(f"cannot parse dependency requirement: {requirement!r}")
    return match.group(1).replace("_", "-").lower()


def collect_project_dependencies(pyproject: dict[str, object]) -> set[str]:
    project = pyproject.get("project")
    if not isinstance(project, dict):
        raise ValueError("pyproject.toml missing [project]")

    names: set[str] = set()
    dependencies = project.get("dependencies", [])
    if not isinstance(dependencies, list):
        raise ValueError("[project].dependencies must be a list")
    names.update(normalize_requirement_name(item) for item in dependencies if isinstance(item, str))

    optional = project.get("optional-dependencies", {})
    if not isinstance(optional, dict):
        raise ValueError("[project.optional-dependencies] must be a table")
    for group_name, group_dependencies in optional.items():
        if not isinstance(group_dependencies, list):
            raise ValueError(f"optional dependency group {group_name!r} must be a list")
        names.update(normalize_requirement_name(item) for item in group_dependencies if isinstance(item, str))

    return names


def collect_build_dependencies(pyproject: dict[str, object]) -> set[str]:
    build_system = pyproject.get("build-system")
    if not isinstance(build_system, dict):
        raise ValueError("pyproject.toml missing [build-system]")
    requires = build_system.get("requires", [])
    if not isinstance(requires, list):
        raise ValueError("[build-system].requires must be a list")
    return {normalize_requirement_name(item) for item in requires if isinstance(item, str)}


def main() -> int:
    pyproject = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))

    project_dependencies = collect_project_dependencies(pyproject)
    build_dependencies = collect_build_dependencies(pyproject)

    unknown_project = sorted(project_dependencies - set(APPROVED_DIRECT_DEPENDENCIES))
    unknown_build = sorted(build_dependencies - set(APPROVED_BUILD_DEPENDENCIES))

    if unknown_project or unknown_build:
        if unknown_project:
            print("ERROR: unapproved direct project dependencies:", ", ".join(unknown_project), file=sys.stderr)
        if unknown_build:
            print("ERROR: unapproved build dependencies:", ", ".join(unknown_build), file=sys.stderr)
        print(
            "Fix: review maintenance, license, security, and size, then update scripts/validate_dependency_policy.py.",
            file=sys.stderr,
        )
        return 1

    print(
        "dependency policy ok: "
        f"project={len(project_dependencies)} build={len(build_dependencies)} "
        "supply-chain audit remains the vulnerability gate"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
