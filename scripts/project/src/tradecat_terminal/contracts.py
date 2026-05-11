from __future__ import annotations

from typing import Any

CONTRACT_VERSION = "1.0.0"

CLI_SCHEMAS = {
    "init": "tradecat.init.v1",
    "doctor": "tradecat.doctor.v1",
    "status": "tradecat.status.v1",
    "path": "tradecat.path_map.v1",
    "datasets": "tradecat.dataset_list.v1",
    "config": "tradecat.config.v1",
    "sync": "tradecat.sync_result.v1",
    "sync-all": "tradecat.sync_results.v1",
    "probe": "tradecat.probe_result.v1",
    "probe-all": "tradecat.probe_results.v1",
    "prune": "tradecat.prune_result.v1",
    "export": "tradecat.dataset_view.v1",
    "analyze": "tradecat.analysis_report.v1",
    "watch": "tradecat.watch_cycle.v1",
}


def schema_for(command: str) -> str:
    return CLI_SCHEMAS.get(command, f"tradecat.{command.replace('-', '_')}.v1")


def attach_contract(payload: dict[str, Any], command: str, *, schema: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema": schema or schema_for(command),
        "schema_version": CONTRACT_VERSION,
        "command": command,
    }
    result.update(payload)
    result.setdefault("ok", True)
    return _normalize_payload_error(result)


def attach_results_contract(
    results: list[dict[str, Any]],
    command: str,
    *,
    result_key: str = "results",
    schema: str | None = None,
) -> dict[str, Any]:
    normalized = [_normalize_payload_error(dict(result)) for result in results]
    return {
        "schema": schema or schema_for(command),
        "schema_version": CONTRACT_VERSION,
        "command": command,
        "ok": all(bool(result.get("ok", True)) for result in normalized),
        result_key: normalized,
    }


def error_contract(
    command: str,
    error: Exception | str,
    *,
    schema: str | None = None,
    code: str = "command_failed",
    kind: str = "validation",
    hint: str = "",
    retryable: bool = False,
) -> dict[str, Any]:
    return attach_contract(
        {
            "ok": False,
            "error": make_error(
                error,
                code=code,
                kind=kind,
                hint=hint,
                retryable=retryable,
            ),
        },
        command,
        schema=schema,
    )


def make_error(
    error: Exception | str | dict[str, Any],
    *,
    code: str = "command_failed",
    kind: str = "validation",
    hint: str = "",
    retryable: bool = False,
) -> dict[str, Any]:
    if isinstance(error, dict):
        raw = dict(error)
        return {
            "code": str(raw.get("code") or code),
            "kind": str(raw.get("kind") or kind),
            "message": str(raw.get("message") or raw.get("error") or code),
            "hint": str(raw.get("hint") or hint),
            "retryable": bool(raw.get("retryable", retryable)),
            **{key: raw[key] for key in ("status", "attempts", "url_host") if key in raw},
        }
    return {
        "code": code,
        "kind": kind,
        "message": str(error),
        "hint": hint,
        "retryable": retryable,
    }


def _normalize_payload_error(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("ok") is not False:
        return payload
    existing = payload.get("error")
    if isinstance(existing, dict):
        payload["error"] = make_error(existing)
        return payload
    error_info = payload.get("error_info")
    if isinstance(error_info, dict):
        payload["error_message"] = str(existing or error_info.get("message") or error_info.get("code") or "")
        payload["error"] = make_error(error_info)
        return payload
    payload["error_message"] = str(existing or "command failed")
    payload["error"] = make_error(
        str(existing or "command failed"),
        code=str(payload.get("error_code") or "command_failed"),
        kind=str(payload.get("error_kind") or "runtime"),
        hint=str(payload.get("error_hint") or ""),
        retryable=bool(payload.get("error_retryable", False)),
    )
    return payload
