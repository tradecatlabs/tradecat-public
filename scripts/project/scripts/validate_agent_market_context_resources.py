from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parents[1]
RESOURCE_ROOT = PROJECT_ROOT / "resources" / "agent_market_context" / "binance"
PROVENANCE_PATH = RESOURCE_ROOT / "provenance.manifest.json"
EXPECTED_SCHEMA = "tradecat.agent_market_context_sources.v1"
EXPECTED_SCHEMA_VERSION = "1.0.0"
REQUIRED_FORBIDDEN = {
    "binance_api_keys",
    "signed_requests",
    "account_reads",
    "real_orders",
    "order_cancel_modify",
    "leverage_or_margin_changes",
}
REQUIRED_ALLOWED_FAMILIES = {
    "klines",
    "order_book_depth",
    "book_ticker",
    "24h_ticker",
    "funding_rate",
    "premium_index",
    "open_interest",
    "open_interest_history",
    "long_short_ratios",
    "taker_buy_sell_volume",
}


def main() -> int:
    errors = validate()
    if errors:
        for error in errors:
            print(f"agent-market-context-resources: ERROR: {error}", file=sys.stderr)
        return 1
    print("agent-market-context-resources: ok")
    return 0


def validate() -> list[str]:
    errors: list[str] = []
    if not PROVENANCE_PATH.exists():
        return [f"missing provenance manifest: {PROVENANCE_PATH.relative_to(PROJECT_ROOT)}"]
    try:
        payload = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"invalid provenance JSON: {exc}"]
    if not isinstance(payload, dict):
        return ["provenance root must be an object"]

    _expect(payload.get("schema") == EXPECTED_SCHEMA, f"schema must be {EXPECTED_SCHEMA}", errors)
    _expect(payload.get("schema_version") == EXPECTED_SCHEMA_VERSION, f"schema_version must be {EXPECTED_SCHEMA_VERSION}", errors)
    _expect(payload.get("destination_root") == "scripts/project/resources/agent_market_context/binance", "destination_root mismatch", errors)

    raw_copy_policy = payload.get("copy_policy")
    copy_policy: dict[str, Any] = raw_copy_policy if isinstance(raw_copy_policy, dict) else {}
    _expect(copy_policy.get("mode") == "read_only_snapshot", "copy_policy.mode must be read_only_snapshot", errors)
    _expect(copy_policy.get("source_files_modified") is False, "source_files_modified must be false", errors)
    _expect(copy_policy.get("symlinked") is False, "copy_policy.symlinked must be false", errors)
    _expect(copy_policy.get("runtime_dependency") is False, "copy_policy.runtime_dependency must be false", errors)

    raw_boundary = payload.get("tradecat_boundary")
    boundary: dict[str, Any] = raw_boundary if isinstance(raw_boundary, dict) else {}
    allowed_modes = set(boundary.get("allowed_modes") or [])
    _expect({"public_readonly", "paper", "watch"}.issubset(allowed_modes), "allowed_modes must include public_readonly/paper/watch", errors)
    forbidden = set(boundary.get("forbidden") or [])
    _expect(REQUIRED_FORBIDDEN.issubset(forbidden), "forbidden boundary list is incomplete", errors)
    families = set(boundary.get("allowed_market_context_families") or [])
    _expect(REQUIRED_ALLOWED_FAMILIES.issubset(families), "allowed_market_context_families is incomplete", errors)

    raw_sources = payload.get("sources")
    sources: list[Any] = raw_sources if isinstance(raw_sources, list) else []
    _expect(bool(sources), "sources must be non-empty", errors)
    for source in sources:
        if not isinstance(source, dict):
            errors.append("source item must be object")
            continue
        destination_text = str(source.get("destination_path") or "")
        destination_path = REPO_ROOT / destination_text
        _expect(_is_inside(destination_path, RESOURCE_ROOT), f"source destination escapes resource root: {destination_text}", errors)
        _expect(destination_path.exists(), f"source destination missing: {destination_text}", errors)
        if destination_path.is_file() and source.get("sha256"):
            _expect(_sha256_file(destination_path) == source.get("sha256"), f"sha256 mismatch: {destination_text}", errors)
        if destination_path.is_dir() and source.get("source_sha256_manifest"):
            count, size, digest = _tree_manifest(destination_path, destination_path)
            _expect(count == source.get("file_count"), f"file_count mismatch: {destination_text}", errors)
            _expect(size == source.get("bytes"), f"bytes mismatch: {destination_text}", errors)
            _expect(digest == source.get("source_sha256_manifest"), f"source_sha256_manifest mismatch: {destination_text}", errors)

    raw_copied_files = payload.get("copied_files")
    copied_files: dict[str, Any] = raw_copied_files if isinstance(raw_copied_files, dict) else {}
    files = [path for path in RESOURCE_ROOT.rglob("*") if path.is_file() and path.name != "provenance.manifest.json"]
    count, size, digest = _tree_manifest(RESOURCE_ROOT, RESOURCE_ROOT, files=files)
    _expect(count == copied_files.get("file_count"), "copied_files.file_count mismatch", errors)
    _expect(size == copied_files.get("bytes"), "copied_files.bytes mismatch", errors)
    _expect(digest == copied_files.get("sha256_manifest"), "copied_files.sha256_manifest mismatch", errors)

    for path in RESOURCE_ROOT.rglob("*"):
        _expect(not path.is_symlink(), f"symlink is not allowed in resource snapshot: {path.relative_to(RESOURCE_ROOT)}", errors)
    return errors


def _tree_manifest(root: Path, base: Path, *, files: list[Path] | None = None) -> tuple[int, int, str]:
    selected = files if files is not None else [path for path in root.rglob("*") if path.is_file()]
    lines: list[str] = []
    total_bytes = 0
    for path in sorted(selected, key=lambda item: item.relative_to(base).as_posix()):
        data = path.read_bytes()
        total_bytes += len(data)
        lines.append(f"{hashlib.sha256(data).hexdigest()}  {path.relative_to(base).as_posix()}  {len(data)}\n")
    return len(selected), total_bytes, hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _expect(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


if __name__ == "__main__":
    raise SystemExit(main())
