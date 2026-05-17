from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

JOURNAL_SCHEMA = "tradecat_auto.audit_journal.v1"
JOURNAL_WRITE_SCHEMA = "tradecat_auto.audit_journal_write.v1"
SCHEMA_VERSION = "1.0.0"
DANGEROUS_REAL_ORDER_KEY_COMPACTS = {
    "account",
    "accountinfo",
    "accountstate",
    "activateprice",
    "allorders",
    "apikey",
    "avgprice",
    "balance",
    "balances",
    "clientorderid",
    "closeposition",
    "cumqty",
    "cumquote",
    "cummulativequoteqty",
    "executedqty",
    "fills",
    "goodtilldate",
    "listenkey",
    "newclientorderid",
    "openorders",
    "orderid",
    "orderlistid",
    "origclientorderid",
    "origqty",
    "position",
    "positionamt",
    "positionrisk",
    "positions",
    "positionside",
    "priceprotect",
    "pricematch",
    "pricerate",
    "reduceonly",
    "secretkey",
    "selftradepreventionmode",
    "signature",
    "stopprice",
    "timeinforce",
    "transacttime",
    "updatetime",
    "usertrades",
    "workingtype",
}
SIGNED_CONTEXT_KEY_COMPACTS = {"apikey", "recvwindow", "requiressignature", "secretkey", "signature", "signed"}


class AuditJournalError(ValueError):
    """Raised when an audit journal write would violate the paper/watch boundary."""


def init_audit_journal(path: Path | str) -> dict[str, Any]:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _connect(db_path) as conn:
        _ensure_schema(conn)
    return {
        "schema": JOURNAL_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "path": str(db_path),
        "storage": "sqlite3_local_audit_journal",
        "safety": _safety_boundary(),
    }


def append_audit_record(
    path: Path | str,
    *,
    event_type: str,
    payload: dict[str, Any],
    run_id: str = "",
    idempotency_key: str = "",
    record_id: str = "",
    created_at: str | None = None,
) -> dict[str, Any]:
    db_path = Path(path)
    created = created_at or _now_iso()
    clean_event_type = str(event_type or "").strip()
    if not clean_event_type:
        raise AuditJournalError("event_type is required")
    clean_payload = payload if isinstance(payload, dict) else {"payload": payload}
    clean_run_id = str(run_id or "").strip()
    if _contains_real_order_payload(clean_payload):
        return _write_error(
            db_path,
            clean_run_id,
            code="real_order_payload_rejected",
            message="audit journal refuses real order/account/credential payloads in tradecat-public",
        )
    payload_json = _canonical_json(clean_payload)
    payload_sha = _sha256(payload_json)
    clean_idempotency_key = str(idempotency_key or "").strip()
    clean_record_id = str(record_id or "").strip() or _record_id(clean_run_id, clean_event_type, clean_idempotency_key, payload_sha)

    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _connect(db_path) as conn:
        _ensure_schema(conn)
        if clean_idempotency_key:
            existing = _get_record_by_idempotency_key(conn, clean_idempotency_key)
            if existing is not None:
                return _record_result(existing, inserted=False, path=db_path)
        previous = _latest_record(conn)
        prev_hash = str(previous["record_sha256"] if previous else "")
        record_hash = _record_hash(
            record_id=clean_record_id,
            run_id=clean_run_id,
            event_type=clean_event_type,
            idempotency_key=clean_idempotency_key,
            payload_sha256=payload_sha,
            prev_record_sha256=prev_hash,
            created_at=created,
        )
        try:
            conn.execute(
                """
                insert into audit_records (
                    record_id, idempotency_key, run_id, event_type, schema_name,
                    schema_version, payload_json, payload_sha256, prev_record_sha256,
                    record_sha256, created_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    clean_record_id,
                    clean_idempotency_key or None,
                    clean_run_id,
                    clean_event_type,
                    str(clean_payload.get("schema") or ""),
                    str(clean_payload.get("schema_version") or ""),
                    payload_json,
                    payload_sha,
                    prev_hash,
                    record_hash,
                    created,
                ),
            )
        except sqlite3.IntegrityError:
            existing = _get_record_by_idempotency_key(conn, clean_idempotency_key) or _get_record_by_id(conn, clean_record_id)
            if existing is not None:
                return _record_result(existing, inserted=False, path=db_path)
            raise
        inserted = _get_record_by_id(conn, clean_record_id)
        if inserted is None:  # pragma: no cover - sqlite invariant guard
            raise AuditJournalError("audit record insert failed")
        return _record_result(inserted, inserted=True, path=db_path)


def record_service_cycle(
    path: Path | str,
    cycle: dict[str, Any],
    *,
    run_id: str,
    config_snapshot: dict[str, Any],
    created_at: str | None = None,
) -> dict[str, Any]:
    db_path = Path(path)
    created = created_at or _now_iso()
    clean_run_id = str(run_id or "").strip() or _run_id(cycle, config_snapshot)
    if _contains_real_order_payload(cycle) or _contains_real_order_payload(config_snapshot):
        return _write_error(
            db_path,
            clean_run_id,
            code="real_order_payload_rejected",
            message="audit journal refuses real order payloads in tradecat-public",
        )
    init_audit_journal(db_path)
    config = config_snapshot if isinstance(config_snapshot, dict) else {}
    _ensure_run(db_path, clean_run_id, config, created_at=created)

    writes: list[tuple[str, dict[str, Any], str]] = []
    writes.append(("run_config_snapshot", _config_payload(config), f"run_config:{clean_run_id}:{_sha256(_canonical_json(config))}"))
    event_id = _event_id(cycle)
    writes.append(("service_cycle", cycle, f"service_cycle:{clean_run_id}:{event_id}:{cycle.get('action')}"))
    raw_pipeline = cycle.get("pipeline_report")
    pipeline: dict[str, Any] = raw_pipeline if isinstance(raw_pipeline, dict) else {}
    raw_risk_decision = pipeline.get("risk_decision")
    risk_decision: dict[str, Any] = raw_risk_decision if isinstance(raw_risk_decision, dict) else {}
    if risk_decision:
        writes.append(("risk_decision", risk_decision, f"risk_decision:{clean_run_id}:{event_id}"))
    for order in _recent_paper_orders(cycle):
        order_id = str(order.get("order_id") or order.get("execution_id") or _sha256(_canonical_json(order)))
        writes.append(("paper_order", order, f"paper_order:{clean_run_id}:{order_id}"))
    for fill in _recent_fills(cycle):
        fill_id = str(fill.get("fill_id") or _sha256(_canonical_json(fill)))
        writes.append(("paper_fill", fill, f"paper_fill:{clean_run_id}:{fill_id}"))

    results = [
        append_audit_record(
            db_path,
            event_type=event_type,
            payload=payload,
            run_id=clean_run_id,
            idempotency_key=idempotency_key,
            created_at=created,
        )
        for event_type, payload, idempotency_key in writes
    ]
    inserted_count = sum(1 for item in results if item.get("inserted"))
    return {
        "schema": JOURNAL_WRITE_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "path": str(db_path),
        "run_id": clean_run_id,
        "records_inserted": inserted_count,
        "records_total": len(results),
        "latest_record_sha256": results[-1].get("record_sha256") if results else "",
        "safety": _safety_boundary(),
    }


def journal_summary(path: Path | str) -> dict[str, Any]:
    """Return a read-only summary of an existing audit journal.

    This function intentionally does not call ``init_audit_journal``. Commands
    advertised as ``writes=false`` must not create SQLite files, WAL files, or
    runtime directories just because an operator asks for a status summary.
    """

    db_path = Path(path)
    if not db_path.exists():
        return _journal_summary_error(
            db_path,
            code="audit_journal_missing",
            message="audit journal does not exist; run a paper/watch cycle first",
            chain_valid=True,
        )
    try:
        with _connect(db_path, read_only=True) as conn:
            event_type_counts = {
                str(row["event_type"]): int(row["count"])
                for row in conn.execute("select event_type, count(*) as count from audit_records group by event_type order by event_type")
            }
            record_count = int(conn.execute("select count(*) from audit_records").fetchone()[0])
            run_count = int(conn.execute("select count(*) from production_runs").fetchone()[0])
            latest = _latest_record(conn)
            integrity = _chain_integrity(conn)
            user_version = int(conn.execute("pragma user_version").fetchone()[0])
    except sqlite3.Error as exc:
        return _journal_summary_error(
            db_path,
            code="audit_journal_load_failed",
            message=f"audit journal read failed: {exc}",
            chain_valid=False,
        )
    return {
        "schema": "tradecat_auto.audit_journal_summary.v1",
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "path": str(db_path),
        "storage": "sqlite3_local_audit_journal",
        "sqlite_user_version": user_version,
        "record_count": record_count,
        "run_count": run_count,
        "event_type_counts": event_type_counts,
        "latest_record_sha256": str(latest["record_sha256"] if latest else ""),
        "chain_valid": integrity["chain_valid"],
        "chain_error": integrity.get("chain_error"),
        "safety": _safety_boundary(),
    }


def _journal_summary_error(path: Path, *, code: str, message: str, chain_valid: bool) -> dict[str, Any]:
    return {
        "schema": "tradecat_auto.audit_journal_summary.v1",
        "schema_version": SCHEMA_VERSION,
        "ok": False,
        "path": str(path),
        "storage": "sqlite3_local_audit_journal",
        "sqlite_user_version": None,
        "record_count": 0,
        "run_count": 0,
        "event_type_counts": {},
        "latest_record_sha256": "",
        "chain_valid": chain_valid,
        "chain_error": None if chain_valid else code,
        "error": {"code": code, "kind": "local_runtime", "message": message, "retryable": code == "audit_journal_missing"},
        "safety": _safety_boundary(),
    }


def _connect(path: Path, *, read_only: bool = False) -> sqlite3.Connection:
    if read_only:
        conn = sqlite3.connect(f"file:{path}?mode=ro", timeout=30.0, uri=True)
    else:
        conn = sqlite3.connect(path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    if not read_only:
        conn.execute("pragma journal_mode=WAL")
    conn.execute("pragma foreign_keys=ON")
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        create table if not exists journal_meta (
            key text primary key,
            value text not null
        );
        create table if not exists production_runs (
            run_id text primary key,
            status text not null,
            started_at text not null,
            finished_at text,
            source text not null,
            config_snapshot_json text not null,
            config_sha256 text not null,
            created_at text not null
        );
        create table if not exists audit_records (
            seq integer primary key autoincrement,
            record_id text not null unique,
            idempotency_key text unique,
            run_id text not null,
            event_type text not null,
            schema_name text not null,
            schema_version text not null,
            payload_json text not null,
            payload_sha256 text not null,
            prev_record_sha256 text not null,
            record_sha256 text not null,
            created_at text not null
        );
        create index if not exists idx_audit_records_run_id on audit_records(run_id);
        create index if not exists idx_audit_records_event_type on audit_records(event_type);
        pragma user_version = 1;
        """
    )
    conn.execute("insert or replace into journal_meta(key, value) values('schema', ?)", (JOURNAL_SCHEMA,))
    conn.execute("insert or replace into journal_meta(key, value) values('schema_version', ?)", (SCHEMA_VERSION,))
    conn.execute("insert or replace into journal_meta(key, value) values('storage', 'sqlite3')")
    conn.commit()


def _ensure_run(path: Path, run_id: str, config_snapshot: dict[str, Any], *, created_at: str) -> None:
    config_json = _canonical_json(config_snapshot)
    with _connect(path) as conn:
        _ensure_schema(conn)
        conn.execute(
            """
            insert or ignore into production_runs (
                run_id, status, started_at, finished_at, source,
                config_snapshot_json, config_sha256, created_at
            ) values (?, 'RUNNING', ?, null, ?, ?, ?, ?)
            """,
            (
                run_id,
                created_at,
                str(config_snapshot.get("source") or "tradecat_auto.service"),
                config_json,
                _sha256(config_json),
                created_at,
            ),
        )
        conn.commit()


def _latest_record(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute("select * from audit_records order by seq desc limit 1").fetchone()


def _get_record_by_idempotency_key(conn: sqlite3.Connection, idempotency_key: str) -> sqlite3.Row | None:
    if not idempotency_key:
        return None
    return conn.execute("select * from audit_records where idempotency_key = ?", (idempotency_key,)).fetchone()


def _get_record_by_id(conn: sqlite3.Connection, record_id: str) -> sqlite3.Row | None:
    return conn.execute("select * from audit_records where record_id = ?", (record_id,)).fetchone()


def _chain_integrity(conn: sqlite3.Connection) -> dict[str, Any]:
    previous_hash = ""
    for row in conn.execute("select * from audit_records order by seq asc"):
        expected = _record_hash(
            record_id=str(row["record_id"]),
            run_id=str(row["run_id"]),
            event_type=str(row["event_type"]),
            idempotency_key=str(row["idempotency_key"] or ""),
            payload_sha256=str(row["payload_sha256"]),
            prev_record_sha256=previous_hash,
            created_at=str(row["created_at"]),
        )
        if str(row["prev_record_sha256"] or "") != previous_hash:
            return {"chain_valid": False, "chain_error": f"prev_hash_mismatch_at_seq_{row['seq']}"}
        if str(row["record_sha256"]) != expected:
            return {"chain_valid": False, "chain_error": f"record_hash_mismatch_at_seq_{row['seq']}"}
        previous_hash = str(row["record_sha256"])
    return {"chain_valid": True, "chain_error": None}


def _record_result(row: sqlite3.Row, *, inserted: bool, path: Path) -> dict[str, Any]:
    return {
        "schema": "tradecat_auto.audit_record_write.v1",
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "inserted": inserted,
        "path": str(path),
        "seq": int(row["seq"]),
        "record_id": str(row["record_id"]),
        "run_id": str(row["run_id"]),
        "event_type": str(row["event_type"]),
        "idempotency_key": str(row["idempotency_key"] or ""),
        "payload_sha256": str(row["payload_sha256"]),
        "prev_record_sha256": str(row["prev_record_sha256"]),
        "record_sha256": str(row["record_sha256"]),
        "created_at": str(row["created_at"]),
        "safety": _safety_boundary(),
    }


def _config_payload(config_snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "tradecat_auto.run_config_snapshot.v1",
        "schema_version": SCHEMA_VERSION,
        "config_snapshot": config_snapshot,
        "config_sha256": _sha256(_canonical_json(config_snapshot)),
        "safety": _safety_boundary(),
    }


def _recent_paper_orders(cycle: dict[str, Any]) -> list[dict[str, Any]]:
    raw_ledger = cycle.get("paper_ledger")
    ledger: dict[str, Any] = raw_ledger if isinstance(raw_ledger, dict) else {}
    orders = ledger.get("recent_paper_orders") or ledger.get("paper_orders") or []
    return [item for item in orders if isinstance(item, dict)]


def _recent_fills(cycle: dict[str, Any]) -> list[dict[str, Any]]:
    raw_ledger = cycle.get("paper_ledger")
    ledger: dict[str, Any] = raw_ledger if isinstance(raw_ledger, dict) else {}
    fills = ledger.get("recent_fills") or ledger.get("fills") or []
    return [item for item in fills if isinstance(item, dict)]


def _contains_real_order_payload(value: Any, *, signed_context: bool = False) -> bool:
    if isinstance(value, dict):
        compact_keys = {_compact_key(key): key for key in value}
        current_signed_context = signed_context or any(
            compact in SIGNED_CONTEXT_KEY_COMPACTS and value.get(original) is not False
            for compact, original in compact_keys.items()
        )
        if value.get("real_order") is True:
            return True
        if value.get("signed_requests") is True:
            return True
        if value.get("reads_api_keys") is True:
            return True
        exchange_order_id = str(value.get("exchange_order_id") or "").strip()
        if exchange_order_id and exchange_order_id.lower() not in {"none", "null"}:
            return True
        for key, child in value.items():
            compact = _compact_key(key)
            if compact in DANGEROUS_REAL_ORDER_KEY_COMPACTS:
                # ``order_id`` / ``position_side`` are TradeCat local paper-order fields.
                # CamelCase Binance fields (``orderId``, ``positionSide``) stay forbidden.
                if not (compact in {"orderid", "positionside"} and "_" in str(key)):
                    return True
            if compact == "timestamp" and current_signed_context:
                return True
            if _contains_real_order_payload(child, signed_context=current_signed_context):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_real_order_payload(item, signed_context=signed_context) for item in value)
    return False


def _compact_key(key: Any) -> str:
    return str(key).lower().replace("-", "_").replace("_", "")


def _write_error(path: Path, run_id: str, *, code: str, message: str) -> dict[str, Any]:
    return {
        "schema": JOURNAL_WRITE_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "ok": False,
        "path": str(path),
        "run_id": run_id,
        "records_inserted": 0,
        "records_total": 0,
        "error": {"code": code, "kind": "safety_boundary", "message": message, "retryable": False},
        "safety": _safety_boundary(),
    }


def _event_id(cycle: dict[str, Any]) -> str:
    raw_latest_event = cycle.get("latest_event")
    latest_event: dict[str, Any] = raw_latest_event if isinstance(raw_latest_event, dict) else {}
    event_id = str(latest_event.get("event_id") or "").strip()
    if event_id:
        return event_id
    return _sha256(_canonical_json(cycle))[:24]


def _run_id(cycle: dict[str, Any], config_snapshot: dict[str, Any]) -> str:
    return _sha256(_canonical_json({"cycle": cycle, "config": config_snapshot}))[:24]


def _record_id(run_id: str, event_type: str, idempotency_key: str, payload_sha256: str) -> str:
    return _sha256("\n".join([run_id, event_type, idempotency_key, payload_sha256]))


def _record_hash(**fields: str) -> str:
    return _sha256(_canonical_json(fields))


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _safety_boundary() -> dict[str, bool]:
    return {
        "public_readonly_market_data": True,
        "public_readonly": True,
        "paper_or_watch_only": True,
        "real_orders": False,
        "signed_requests": False,
        "reads_api_keys": False,
        "binance_account_state": False,
    }
