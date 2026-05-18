from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import Any

from tradecat_terminal.analysis import DEFAULT_CANDIDATE_LIMIT, build_analysis_report
from tradecat_terminal.contracts import make_error


def build_feature_bundle(
    cache_dir: Path,
    *,
    analysis_window: str = "24h",
    symbol_limit: int = DEFAULT_CANDIDATE_LIMIT,
) -> dict[str, Any]:
    """生成按 symbol 归一化的结构化事实层。

    feature_bundle.v1 只表达可验证事实，不做分数、策略、回测或交易执行。
    """
    analysis = build_analysis_report(cache_dir, analysis_window=analysis_window, candidate_limit=symbol_limit)
    base = {
        "generated_at": analysis.get("generated_at", ""),
        "feature_window": {
            "requested": (analysis.get("analysis_window") or {}).get("requested", analysis_window),
            "mode": "latest_cached",
            "source_schema": "tradecat.analysis_report.v1",
            "dataset_keys": list((analysis.get("analysis_window") or {}).get("dataset_keys") or []),
        },
        "dataset_freshness": list(analysis.get("dataset_freshness") or []),
        "symbols": [],
        "evidence": list(analysis.get("evidence") or []),
        "risk_flags": _bundle_risk_flags(analysis),
        "limitations": _bundle_limitations(),
    }

    if not analysis.get("ok"):
        return {
            **base,
            "ok": False,
            "error": make_error(
                "本地缓存没有可生成 feature bundle 的候选标的。",
                code="empty_feature_cache",
                kind="local_state",
                hint="先运行 bash scripts/run-tradecat.sh doctor --sync --timeout 10 或 sync-all --json 预热本地缓存。",
                retryable=True,
            ),
        }

    candidates = [item for item in analysis.get("candidate_symbols") or [] if isinstance(item, dict)]
    if not candidates:
        return {
            **base,
            "ok": False,
            "error": make_error(
                "analysis_report 未暴露可归一化的候选标的。",
                code="empty_feature_cache",
                kind="local_state",
                hint="确认 anomaly_panel 本地缓存包含带交易对字段的行，或先执行 doctor --sync 预热缓存。",
                retryable=True,
            ),
        }

    observations = {str(item.get("id")): item for item in analysis.get("observations") or [] if isinstance(item, dict)}
    symbols = [
        _symbol_features(candidate, analysis, observations)
        for candidate in candidates[:symbol_limit]
        if str(candidate.get("symbol") or "").strip()
    ]
    if not symbols:
        return {
            **base,
            "ok": False,
            "error": make_error(
                "候选标的缺少可用 symbol。",
                code="empty_feature_cache",
                kind="local_state",
                hint="确认 anomaly_panel 的 entity_key 字段存在且非空。",
                retryable=True,
            ),
        }

    return {
        **base,
        "ok": True,
        "symbols": symbols,
    }


def _symbol_features(
    candidate: dict[str, Any],
    analysis: dict[str, Any],
    observations: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    evidence_ids = _strings(candidate.get("evidence_ids"))
    source_dataset_keys = _strings(candidate.get("source_dataset_keys"))
    features: list[dict[str, Any]] = []
    if "signal_flow" in source_dataset_keys:
        features.append(
            _symbol_presence_feature(
                "signal_flow.presence",
                "signal_flow",
                _evidence_ids_for_dataset(evidence_ids, "signal_flow"),
                "Symbol appears in signal_flow explicit entity-key fields.",
            )
        )
    if "anomaly_panel" in source_dataset_keys:
        features.append(
            _symbol_presence_feature(
                "anomaly_panel.presence",
                "anomaly_panel",
                _evidence_ids_for_dataset(evidence_ids, "anomaly_panel"),
                "Symbol appears in anomaly_panel explicit entity-key fields.",
            )
        )

    return {
        "symbol": str(candidate.get("symbol") or "").strip(),
        "features": features,
        "source_dataset_keys": _dedupe(
            [
                *[dataset for feature in features for dataset in _strings(feature.get("source_dataset_keys"))],
                *_strings(candidate.get("source_dataset_keys")),
            ]
        ),
        "freshness": list(analysis.get("dataset_freshness") or []),
        "evidence_ids": _dedupe([evidence_id for feature in features for evidence_id in _strings(feature.get("evidence_ids"))]),
        "confidence": str(candidate.get("confidence") or "observed"),
        "risk_flags": _symbol_risk_flags(),
        "limitations": _bundle_limitations(),
    }


def _symbol_presence_feature(name: str, dataset_key: str, evidence_ids: list[str], description: str) -> dict[str, Any]:
    return {
        "name": name,
        "kind": "symbol_observation",
        "value": True,
        "value_type": "boolean",
        "source_dataset_keys": [dataset_key],
        "evidence_ids": evidence_ids,
        "confidence": "observed",
        "description": description,
    }


def _context_feature(name: str, dataset_key: str, observation: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": name,
        "kind": "context_observation",
        "value": True,
        "value_type": "boolean",
        "source_dataset_keys": [dataset_key],
        "evidence_ids": _strings(observation.get("evidence_ids")),
        "confidence": "observed",
        "description": f"{dataset_key} provides cached context for this feature bundle.",
    }


def _bundle_risk_flags(analysis: dict[str, Any]) -> list[dict[str, str]]:
    inherited = [item for item in analysis.get("risk_flags") or [] if isinstance(item, dict)]
    return [
        *inherited,
        {
            "code": "feature_bundle_not_signal",
            "severity": "warning",
            "message": "feature_bundle.v1 只表达结构化事实，不表达分数、策略、收益预测或交易建议。",
        },
    ]


def _symbol_risk_flags() -> list[dict[str, str]]:
    return [
        {
            "code": "symbol_features_observed_only",
            "severity": "warning",
            "message": "该 symbol 的 features 只表示本地缓存中可验证的观察事实，不代表交易方向。",
        }
    ]


def _bundle_limitations() -> list[str]:
    return [
        "只读取本地最新缓存，不联网同步，不写缓存。",
        "只把 analysis_report.v1 的候选和证据归一化为 symbol facts。",
        "不输出评分、策略、回测、收益预测、买卖建议或自动交易执行语义。",
    ]


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _dedupe(values: list[str]) -> list[str]:
    return list(OrderedDict((value, None) for value in values if value))


def _evidence_ids_for_dataset(evidence_ids: list[str], dataset_key: str) -> list[str]:
    prefix = f"{dataset_key}:"
    return [evidence_id for evidence_id in evidence_ids if evidence_id.startswith(prefix)]
