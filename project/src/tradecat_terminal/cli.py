from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

from tradecat_terminal.analysis import build_analysis_report
from tradecat_terminal.cache import init_cache, prune_cache, status_cache
from tradecat_terminal.config import load_config
from tradecat_terminal.contracts import attach_contract, attach_results_contract, error_contract
from tradecat_terminal.diagnostics import bundle_to_json, write_support_bundle
from tradecat_terminal.features import build_feature_bundle
from tradecat_terminal.i18n import LANG_ENV, resolve_lang, tr
from tradecat_terminal.lifecycle import doctor_local_store, probe_all_datasets, probe_dataset, watch_datasets
from tradecat_terminal.registry import UnknownDatasetError, dataset_to_dict, get_dataset, list_datasets
from tradecat_terminal.settings import load_settings, set_setting, settings_path, unset_setting
from tradecat_terminal.sync import sync_all_datasets, sync_dataset
from tradecat_terminal.tui import render_rows_table, run_tui
from tradecat_terminal.view_model import build_dataset_view

TUI_NO_PAUSE_ENV = "TRADECAT_TERMINAL_NO_PAUSE"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tradecat", description="TradeCat 用户侧终端面板")
    parser.add_argument("--cache-dir", help="本地快照缓存目录，默认 TRADECAT_CACHE_DIR 或 TradeCat 源码根目录 .tradecat/cache")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="初始化本地快照缓存目录")
    init_parser.add_argument("--json", action="store_true", help="输出 JSON")

    doctor_parser = subparsers.add_parser("doctor", help="检查本地缓存状态")
    doctor_parser.add_argument("--json", action="store_true", help="输出 JSON")
    doctor_parser.add_argument("--fix", action="store_true", help="只修复本地目录骨架，不触发远端同步")
    doctor_parser.add_argument("--repair", action="store_true", help="修复本地目录并执行安全 metadata 迁移，不触发远端同步")
    doctor_parser.add_argument("--verbose", action="store_true", help="输出更完整的本地诊断摘要")
    doctor_parser.add_argument(
        "--bundle",
        nargs="?",
        const="-",
        metavar="PATH",
        help="生成公开安全诊断包 JSON；不传 PATH 时输出到 stdout",
    )
    doctor_parser.add_argument("--sync", action="store_true", help="显式同步全部 active dataset，修复首次空缓存")
    doctor_parser.add_argument("--timeout", type=_positive_float_arg, help="doctor --sync 时的单次远端请求超时秒数")

    status_parser = subparsers.add_parser("status", help="查看本地缓存状态")
    status_parser.add_argument("--json", action="store_true", help="输出 JSON")

    path_parser = subparsers.add_parser("path", help="输出结构化缓存文件路径，便于用户和 Agent 读取")
    path_parser.add_argument("dataset_key", nargs="?", help="可选 dataset_key；不传则输出根 manifest")
    path_parser.add_argument("--json", action="store_true", help="输出 JSON")

    datasets_parser = subparsers.add_parser("datasets", help="列出可同步 dataset")
    datasets_parser.add_argument("--all", action="store_true", help="包含 inactive dataset")
    datasets_parser.add_argument("--json", action="store_true", help="输出 JSON")

    config_parser = subparsers.add_parser("config", help="查看或修改用户侧本地配置")
    config_parser.add_argument("action", nargs="?", choices=["show", "set", "unset"], default="show")
    config_parser.add_argument("key", nargs="?", help="配置键，例如 default_lang / default_dataset / cache_dir")
    config_parser.add_argument("value", nargs="?", help="配置值")
    config_parser.add_argument("--json", action="store_true", help="输出 JSON")

    sync_parser = subparsers.add_parser("sync", help="按 registry 同步一个 dataset 到本地快照缓存")
    sync_parser.add_argument("dataset_key", help="dataset_key，例如 market_snapshot")
    sync_parser.add_argument("--timeout", type=_positive_float_arg, help="单次远端请求超时秒数")
    sync_parser.add_argument("--json", action="store_true", help="输出 JSON")

    sync_all_parser = subparsers.add_parser("sync-all", help="同步全部 active dataset 到本地快照缓存")
    sync_all_parser.add_argument("--timeout", type=_positive_float_arg, help="每个 dataset 的单次远端请求超时秒数")
    sync_all_parser.add_argument("--json", action="store_true", help="输出 JSON")

    probe_parser = subparsers.add_parser("probe", help="探测远端变化；发现变化后写入本地快照缓存")
    probe_parser.add_argument("dataset_key", nargs="?", help="可选 dataset_key；不传则探测全部 active dataset")
    probe_parser.add_argument("--no-write", action="store_true", help="只做 dry-run，不写缓存")
    probe_parser.add_argument("--timeout", type=_positive_float_arg, help="写缓存探测时的单次远端请求超时秒数")
    probe_parser.add_argument("--json", action="store_true", help="输出 JSON")

    prune_parser = subparsers.add_parser("prune", help="按保留数量裁剪本地历史快照；默认 dry-run 不删除")
    prune_parser.add_argument("dataset_key", nargs="?", help="可选 dataset_key；不传则检查全部 dataset")
    prune_parser.add_argument(
        "--max-snapshots",
        type=int,
        help="每个 dataset 最多保留快照数；默认读取 TRADECAT_CACHE_MAX_SNAPSHOTS，未设置则不启用",
    )
    prune_parser.add_argument("--apply", action="store_true", help="实际删除候选快照；不加则只预览")
    prune_parser.add_argument("--json", action="store_true", help="输出 JSON")

    export_parser = subparsers.add_parser("export", help="从本地缓存导出当前 dataset 视图")
    export_parser.add_argument("dataset_key", help="dataset_key，例如 signal_flow")
    export_parser.add_argument("--format", choices=["json", "jsonl", "csv", "table"], default="json")
    export_parser.add_argument("--limit", type=int, default=0, help="最多导出行数；0 表示不限制")
    export_parser.add_argument("--output", help="输出文件；不传则输出 stdout")
    export_parser.add_argument("--lang", choices=["zh", "en", "ko"], help=f"导出表头显示语言；默认读取 {LANG_ENV} 或配置")

    analyze_parser = subparsers.add_parser("analyze", help="从本地缓存生成 Agent 可消费分析报告")
    analyze_parser.add_argument("--json", action="store_true", help="输出 JSON")
    analyze_parser.add_argument("--window", default="24h", help="分析窗口元数据：latest 或 24h/7d/4w")
    analyze_parser.add_argument("--limit", type=int, default=20, help="最多输出候选标的数量")

    features_parser = subparsers.add_parser("features", help="从本地分析报告生成按 symbol 归一化的事实包")
    features_parser.add_argument("--json", action="store_true", help="输出 JSON")
    features_parser.add_argument("--window", default="24h", help="窗口元数据：latest 或 24h/7d/4w")
    features_parser.add_argument("--limit", type=int, default=20, help="最多输出 symbol 数量")

    auto_parser = subparsers.add_parser("auto", help="运行 TradeCat 全生命周期自动化子命令")
    auto_parser.add_argument("auto_args", nargs=argparse.REMAINDER, help="传给 tradecat_auto.cli 的参数")

    watch_parser = subparsers.add_parser("watch", help="持续探测远端变化并写入本地快照缓存")
    watch_parser.add_argument("dataset_key", nargs="?", help="可选 dataset_key；不传则持续探测全部 active dataset")
    watch_parser.add_argument("--interval", type=float, default=60.0, help="探测间隔秒数")
    watch_parser.add_argument("--max-cycles", type=int, help="最多循环次数；用于测试或一次性运行")
    watch_parser.add_argument("--no-write", action="store_true", help="只持续探测不写缓存")
    watch_parser.add_argument("--json", action="store_true", help="每轮输出 JSON")

    tui_parser = subparsers.add_parser("tui", help="打开终端浏览面板")
    tui_parser.add_argument("dataset_key", nargs="?", help="可选 dataset_key，例如 signal_flow")
    tui_parser.add_argument("--limit", type=int, default=0, help="展示行数；0 表示按屏幕高度自动分页")
    tui_parser.add_argument("--plain", action="store_true", help="输出静态文本，不进入交互式 TUI")
    tui_parser.add_argument("--no-live", action="store_true", help="不启动实时探针，只浏览本地缓存")
    tui_parser.add_argument("--probe-interval", type=float, help="实时探针间隔秒数")
    tui_parser.add_argument("--lang", choices=["zh", "en", "ko"], help=f"TUI 语言；默认读取 {LANG_ENV} 或系统 locale")

    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    if _should_default_to_tui(raw_argv):
        raw_argv = [*raw_argv, "tui"]
    elif _should_route_to_tui(raw_argv):
        raw_argv = _route_global_tui_args(raw_argv)

    args = build_parser().parse_args(raw_argv)
    config = load_config(args.cache_dir)

    if args.command == "auto":
        from tradecat_auto.cli import main as auto_main

        return auto_main(list(args.auto_args or []))

    if args.command == "init":
        payload = init_cache(config.cache_dir)
        _print_json_or_text(attach_contract(payload, "init"), args.json, f"initialized: cache={config.cache_dir}")
        return 0

    if args.command == "doctor":
        if args.timeout is not None and not args.sync:
            return _command_error(
                "doctor",
                "--timeout 仅用于 --sync",
                as_json=args.json,
                code="invalid_timeout_option",
                hint="只有执行 doctor --sync 时才允许指定 --timeout。",
            )
        payload = doctor_local_store(
            config.cache_dir,
            fix=args.fix,
            repair=args.repair,
            sync=args.sync,
            fetch_timeout=args.timeout,
            verbose=args.verbose,
            bundle=args.bundle is not None,
        )
        if args.bundle is not None:
            support_bundle = dict(payload.get("support_bundle") or {})
            if args.bundle == "-":
                print(bundle_to_json(support_bundle), end="")
            else:
                target = write_support_bundle(Path(args.bundle), support_bundle)
                print(f"bundle: {target}")
        elif args.json:
            _print_json(attach_contract(payload, "doctor"))
        else:
            print_status(payload)
        return 0 if payload["ok"] else 1

    if args.command == "status":
        payload = status_cache(config.cache_dir)
        if args.json:
            _print_json(attach_contract(payload, "status"))
        else:
            print_status(payload)
        return 0

    if args.command == "path":
        try:
            payload = cache_paths(config.cache_dir, args.dataset_key)
        except UnknownDatasetError as exc:
            return _command_error(
                "path",
                exc,
                as_json=args.json,
                code="invalid_dataset_key",
                hint="先执行 tradecat datasets --json 查看可用 dataset_key。",
            )
        except Exception as exc:
            return _runtime_command_error("path", exc, as_json=args.json)
        if args.json:
            _print_json(attach_contract(payload, "path"))
        else:
            print_paths(payload)
        return 0

    if args.command == "datasets":
        datasets = [dataset_to_dict(dataset) for dataset in list_datasets(include_inactive=args.all)]
        if args.json:
            _print_json(attach_results_contract(datasets, "datasets", result_key="datasets"))
        else:
            print_datasets(datasets)
        return 0

    if args.command == "config":
        try:
            payload = handle_config_command(args.action, args.key, args.value)
        except ValueError as exc:
            return _command_error(
                "config",
                exc,
                as_json=args.json,
                code="invalid_config_request",
                hint="执行 tradecat config show 查看当前配置；set/unset 需要合法 key。",
            )
        if args.json:
            _print_json(attach_contract(payload, "config"))
        else:
            print_config(payload)
        return 0

    if args.command == "sync":
        try:
            payload = sync_dataset(config.cache_dir, args.dataset_key, fetch_timeout=args.timeout)
        except UnknownDatasetError as exc:
            return _command_error(
                "sync",
                exc,
                as_json=args.json,
                code="invalid_dataset_key",
                hint="先执行 tradecat datasets --json 查看可用 dataset_key。",
            )
        except ValueError as exc:
            return _command_error(
                "sync",
                exc,
                as_json=args.json,
                code="invalid_runtime_configuration",
                hint="检查本地配置、环境变量和缓存压缩参数后重试。",
                kind="configuration",
            )
        except Exception as exc:
            return _runtime_command_error("sync", exc, as_json=args.json)
        if args.json:
            _print_json(attach_contract(payload, "sync"))
        else:
            print_sync(payload)
        return 0 if payload.get("ok") else 1

    if args.command == "sync-all":
        results = sync_all_datasets(config.cache_dir, fetch_timeout=args.timeout)
        if args.json:
            _print_json(attach_results_contract(results, "sync-all"))
        else:
            for result in results:
                print_sync(result)
        return 0 if all(result.get("ok") for result in results) else 1

    if args.command == "probe":
        try:
            if args.dataset_key:
                payload: dict | list = probe_dataset(
                    config.cache_dir,
                    args.dataset_key,
                    write=not args.no_write,
                    fetch_timeout=args.timeout,
                )
            else:
                payload = probe_all_datasets(config.cache_dir, write=not args.no_write, fetch_timeout=args.timeout)
        except UnknownDatasetError as exc:
            return _command_error(
                "probe",
                exc,
                as_json=args.json,
                code="invalid_dataset_key",
                hint="先执行 tradecat datasets --json 查看可用 dataset_key。",
            )
        except ValueError as exc:
            return _command_error(
                "probe",
                exc,
                as_json=args.json,
                code="invalid_runtime_configuration",
                hint="检查本地配置、环境变量和缓存压缩参数后重试。",
                kind="configuration",
            )
        except Exception as exc:
            return _runtime_command_error("probe", exc, as_json=args.json)
        if args.json:
            if isinstance(payload, list):
                _print_json(attach_results_contract(payload, "probe-all"))
            else:
                _print_json(attach_contract(payload, "probe"))
        else:
            print_probe(payload)
        return _payload_exit_code(payload)

    if args.command == "prune":
        try:
            payload = prune_cache(
                config.cache_dir,
                dataset_key=args.dataset_key,
                max_snapshots_per_dataset=_resolve_max_snapshots(args.max_snapshots),
                apply=args.apply,
            )
        except UnknownDatasetError as exc:
            return _command_error(
                "prune",
                exc,
                as_json=args.json,
                code="invalid_dataset_key",
                hint="先执行 tradecat datasets --json 查看可用 dataset_key。",
            )
        except ValueError as exc:
            return _command_error(
                "prune",
                exc,
                as_json=args.json,
                code="invalid_prune_request",
                hint="先执行 tradecat datasets --json 查看可用 dataset_key，并确认 --max-snapshots 为整数。",
            )
        except Exception as exc:
            return _runtime_command_error("prune", exc, as_json=args.json)
        if args.json:
            _print_json(attach_contract(payload, "prune"))
        else:
            print_prune(payload)
        return 0 if payload.get("ok") else 1

    if args.command == "export":
        try:
            payload = export_view(
                config.cache_dir,
                args.dataset_key,
                output_format=args.format,
                limit=args.limit,
                lang=args.lang,
            )
        except UnknownDatasetError as exc:
            return _command_error(
                "export",
                exc,
                as_json=args.format == "json",
                code="invalid_dataset_key",
                hint="先执行 tradecat datasets --json 查看可用 dataset_key。",
            )
        except ValueError as exc:
            return _command_error(
                "export",
                exc,
                as_json=args.format == "json",
                code="invalid_export_request",
                hint="检查导出参数、本地缓存状态和环境配置后重试。",
            )
        except Exception as exc:
            return _runtime_command_error("export", exc, as_json=args.format == "json")
        if args.output:
            output_path = Path(args.output).expanduser()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(payload, encoding="utf-8")
        else:
            print(payload, end="" if payload.endswith("\n") else "\n")
        return 0

    if args.command == "analyze":
        try:
            payload = build_analysis_report(
                config.cache_dir,
                analysis_window=args.window,
                candidate_limit=args.limit,
            )
        except ValueError as exc:
            return _command_error(
                "analyze",
                exc,
                as_json=args.json,
                code="invalid_analysis_request",
                hint="检查 --window 是否为 latest/24h/7d/4w，且 --limit 大于 0。",
            )
        except Exception as exc:
            return _runtime_command_error("analyze", exc, as_json=args.json)
        if args.json:
            _print_json(attach_contract(payload, "analyze"))
        else:
            print_analysis(payload)
        return 0 if payload.get("ok") else 1

    if args.command == "features":
        try:
            payload = build_feature_bundle(
                config.cache_dir,
                analysis_window=args.window,
                symbol_limit=args.limit,
            )
        except ValueError as exc:
            return _command_error(
                "features",
                exc,
                as_json=args.json,
                code="invalid_feature_request",
                hint="检查 --window 是否为 latest/24h/7d/4w，且 --limit 大于 0。",
            )
        except Exception as exc:
            return _runtime_command_error("features", exc, as_json=args.json)
        if args.json:
            _print_json(attach_contract(payload, "features"))
        else:
            print_features(payload)
        return 0 if payload.get("ok") else 1

    if args.command == "watch":
        if args.interval <= 0:
            return _command_error(
                "watch",
                "--interval 必须大于 0",
                as_json=args.json,
                code="invalid_runtime_configuration",
                hint="检查 watch 参数后重试；持续探测间隔必须是正数。",
                kind="configuration",
            )
        if args.max_cycles is not None and args.max_cycles < 1:
            return _command_error(
                "watch",
                "--max-cycles 必须大于 0",
                as_json=args.json,
                code="invalid_runtime_configuration",
                hint="检查 watch 参数后重试；--max-cycles 必须至少为 1。",
                kind="configuration",
            )
        try:
            cycles = watch_datasets(
                config.cache_dir,
                dataset_key=args.dataset_key,
                interval_seconds=args.interval,
                max_cycles=args.max_cycles,
                write=not args.no_write,
            )
        except UnknownDatasetError as exc:
            return _command_error(
                "watch",
                exc,
                as_json=args.json,
                code="invalid_dataset_key",
                hint="先执行 tradecat datasets --json 查看可用 dataset_key。",
            )
        except ValueError as exc:
            return _command_error(
                "watch",
                exc,
                as_json=args.json,
                code="invalid_runtime_configuration",
                hint="检查本地配置、环境变量和 watch 参数后重试。",
                kind="configuration",
            )
        except Exception as exc:
            return _runtime_command_error("watch", exc, as_json=args.json)
        if args.json:
            for index, results in enumerate(cycles, start=1):
                payload = attach_results_contract(results, "watch")
                payload["cycle"] = index
                _print_json(payload)
        else:
            for index, results in enumerate(cycles, start=1):
                print(f"cycle={index}")
                print_probe(results)
        return 0 if all(_payload_ok(result) for results in cycles for result in results) else 1

    if args.command == "tui":
        output = run_tui(
            config.cache_dir,
            dataset_key=args.dataset_key,
            limit=args.limit,
            interactive=not args.plain,
            live=not args.no_live,
            probe_interval_seconds=args.probe_interval,
            lang=args.lang,
        )
        if output is not None:
            print(output)
            _pause_after_interactive_fallback(enabled=not args.plain, lang=args.lang)
        return 0

    return 2


def print_status(payload: dict) -> None:
    print(f"ok: {payload.get('ok')}")
    print(f"cache_dir: {payload.get('cache_dir')}")
    print(f"exists: {payload.get('exists', True)}")
    print(
        "summary: "
        f"datasets={payload.get('dataset_count', 0)} "
        f"ready={payload.get('ready_dataset_count', 0)} "
        f"missing={payload.get('missing_dataset_count', 0)} "
        f"bytes={payload.get('cache_bytes', 0)}"
    )
    for dataset in payload.get("datasets", []):
        print(
            "dataset: "
            f"{dataset['dataset_key']} mode={dataset['data_mode']} active={dataset['active']} "
            f"state={dataset.get('cache_state')} latest={dataset.get('latest_json_exists')} "
            f"snapshots={dataset['snapshot_count']} events={dataset['event_count']} "
            f"rows={dataset['row_count']} cols={dataset['column_count']} bytes={dataset.get('cache_bytes', 0)} "
            f"fetched_at={dataset.get('fetched_at')}"
        )
    for fixed in payload.get("fixes", []):
        print(f"fixed: {fixed}")
    for result in payload.get("sync_results", []):
        print_sync(result)
    if payload.get("settings_health"):
        settings = payload["settings_health"]
        print(f"settings: status={settings.get('status')} path={settings.get('path')}")
    if payload.get("migration"):
        migration = payload["migration"]
        print(f"migration: needed={migration.get('needed')} pending={migration.get('pending_count')}")
    if payload.get("disk_waterline"):
        waterline = payload["disk_waterline"]
        print(
            "disk: "
            f"level={waterline.get('level')} bytes={waterline.get('cache_bytes')} "
            f"warn={waterline.get('warn_bytes')}"
        )
    for item in payload.get("recent_errors", []):
        error = item.get("error") if isinstance(item, dict) else {}
        if isinstance(error, dict):
            print(
                "recent-error: "
                f"dataset={item.get('dataset_key')} code={error.get('code')} "
                f"retryable={error.get('retryable')} at={item.get('at')}",
                file=sys.stderr,
            )
    for warning in payload.get("warnings", []):
        print(f"warning: {warning}", file=sys.stderr)
    for hint in payload.get("repair_hints", []):
        print(f"hint: {hint}", file=sys.stderr)
    for error in payload.get("errors", []):
        print(f"error: {error}", file=sys.stderr)


def print_datasets(datasets: list[dict]) -> None:
    for dataset in datasets:
        print(
            f"{dataset['key']}\tactive={dataset['active']}\tmode={dataset['data_mode']}\t"
            f"workbook={dataset['workbook_key']}\ttab={dataset['tab_name']}\tgid={dataset['gid']}"
        )


def print_sync(payload: dict) -> None:
    if not payload.get("ok"):
        hint = f" hint={payload.get('error_hint')}" if payload.get("error_hint") else ""
        code = f" code={payload.get('error_code')}" if payload.get("error_code") else ""
        print(f"failed: dataset={payload.get('dataset_key')}{code} error={payload.get('error')}{hint}", file=sys.stderr)
        return
    print(
        "synced: "
        f"dataset={payload['dataset_key']} mode={payload['data_mode']} status={payload['status']} "
        f"changed={payload['changed']} rows={payload['row_count']} cols={payload['column_count']} "
        f"cache={payload['cache_dir']}"
    )


def print_probe(payload: dict | list) -> None:
    results = payload if isinstance(payload, list) else [payload]
    for result in results:
        print(
            "probe: "
            f"dataset={result['dataset_key']} status={result['status']} "
            f"changed={result['changed']} wrote={result['wrote']}"
        )
        if result.get("error"):
            hint = f" hint={result.get('error_hint')}" if result.get("error_hint") else ""
            code = f" code={result.get('error_code')}" if result.get("error_code") else ""
            print(f"error:{code} {result['error']}{hint}", file=sys.stderr)


def print_prune(payload: dict) -> None:
    mode = "apply" if payload.get("applied") else "dry-run"
    print(
        f"prune: mode={mode} cache={payload.get('cache_dir')} "
        f"max_snapshots={payload.get('max_snapshots_per_dataset')}"
    )
    for item in payload.get("datasets", []):
        print(
            f"dataset={item['dataset_key']}\tsnapshots={item['snapshot_count']}\t"
            f"keep={item.get('keep_count', item['snapshot_count'])}\t"
            f"candidates={item['candidate_count']}\tdeleted={item['deleted_count']}"
        )


def print_analysis(payload: dict) -> None:
    print(f"ok: {payload.get('ok')}")
    print(f"generated_at: {payload.get('generated_at')}")
    window = payload.get("analysis_window") if isinstance(payload.get("analysis_window"), dict) else {}
    print(f"window: {window.get('requested')} mode={window.get('mode')}")
    for item in payload.get("dataset_freshness", []):
        print(
            "dataset: "
            f"{item.get('dataset_key')} state={item.get('cache_state')} rows={item.get('row_count')} "
            f"fetched_at={item.get('fetched_at')}"
        )
    for observation in payload.get("observations", []):
        print(f"observation: {observation.get('id')} {observation.get('summary')}")
    for candidate in payload.get("candidate_symbols", []):
        print(f"candidate: {candidate.get('rank')}\t{candidate.get('symbol')}")
    if payload.get("error"):
        error = payload["error"]
        print(f"error: code={error.get('code')} message={error.get('message')}", file=sys.stderr)


def print_features(payload: dict) -> None:
    print(f"ok: {payload.get('ok')}")
    print(f"generated_at: {payload.get('generated_at')}")
    window = payload.get("feature_window") if isinstance(payload.get("feature_window"), dict) else {}
    print(f"window: {window.get('requested')} mode={window.get('mode')}")
    for item in payload.get("symbols", []):
        print(
            "symbol: "
            f"{item.get('symbol')} features={len(item.get('features') or [])} "
            f"confidence={item.get('confidence')}"
        )
    if payload.get("error"):
        error = payload["error"]
        print(f"error: code={error.get('code')} message={error.get('message')}", file=sys.stderr)


def handle_config_command(action: str, key: str | None, value: str | None) -> dict:
    if action == "show":
        return {"ok": True, "path": str(settings_path()), "settings": load_settings()}
    if action == "set":
        if not key or value is None:
            raise ValueError("config set 需要 key 和 value")
        return {"ok": True, "path": str(settings_path()), "settings": set_setting(key, value)}
    if action == "unset":
        if not key:
            raise ValueError("config unset 需要 key")
        return {"ok": True, "path": str(settings_path()), "settings": unset_setting(key)}
    raise ValueError(f"未知 config action: {action}")


def print_config(payload: dict) -> None:
    print(f"path: {payload['path']}")
    settings = payload.get("settings") or {}
    if not settings:
        print("settings: {}")
        print("常用键：default_lang, default_dataset, cache_dir, tui_probe_interval_seconds")
        print("单 tap 键：tui_probe_interval.signal_flow, tui_fetch_timeout.signal_flow")
        return
    print(json.dumps(settings, ensure_ascii=False, indent=2, sort_keys=True))


def _positive_float_arg(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("必须是数字") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("必须大于 0")
    return parsed


def export_view(
    cache_dir,
    dataset_key: str,
    *,
    output_format: str,
    limit: int,
    lang: str | None,
) -> str:
    if limit < 0:
        raise ValueError("--limit 必须大于等于 0")
    view = build_dataset_view(cache_dir, dataset_key, lang=lang)
    rows = list(view.get("rows") or [])
    if limit > 0:
        rows = rows[:limit]
    if output_format == "json":
        payload = {
            "ok": True,
            "dataset_key": view.get("dataset_key"),
            "display_name": view.get("display_name"),
            "columns": view.get("columns"),
            "raw_columns": view.get("raw_columns"),
            "meta": view.get("meta"),
            "rows": rows,
        }
        return json.dumps(attach_contract(payload, "export"), ensure_ascii=False, indent=2) + "\n"
    if output_format == "jsonl":
        return "".join(json.dumps(row.get("raw_values") or row.get("values") or {}, ensure_ascii=False) + "\n" for row in rows)
    if output_format == "csv":
        output = []
        writer = csv.DictWriter(_ListWriter(output), fieldnames=list(view.get("raw_columns") or []), lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row.get("raw_values") or {})
        return "".join(output)
    return render_rows_table(rows, columns=list(view.get("columns") or [])) + "\n"


class _ListWriter:
    def __init__(self, output: list[str]) -> None:
        self.output = output

    def write(self, value: str) -> int:
        self.output.append(value)
        return len(value)


def _print_json_or_text(payload: dict, as_json: bool, text: str) -> None:
    if as_json:
        _print_json(payload)
    else:
        print(text)


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False))


def _command_error(
    command: str,
    error: Exception | str,
    *,
    as_json: bool,
    code: str,
    hint: str,
    kind: str = "validation",
    retryable: bool = False,
) -> int:
    if as_json:
        _print_json(
            error_contract(
                command,
                error,
                code=code,
                kind=kind,
                hint=hint,
                retryable=retryable,
            )
        )
    else:
        print(f"{command} error: {error}", file=sys.stderr)
    return 2


def _runtime_command_error(command: str, error: Exception, *, as_json: bool) -> int:
    if as_json:
        _print_json(
            error_contract(
                command,
                error,
                code="local_runtime_error",
                kind="runtime",
                hint="执行 tradecat doctor --verbose 或 doctor --bundle - 获取本地诊断信息。",
                retryable=False,
            )
        )
    else:
        print(f"{command} error: {error}", file=sys.stderr)
    return 1


def _payload_exit_code(payload: dict | list) -> int:
    results = payload if isinstance(payload, list) else [payload]
    return 0 if all(_payload_ok(result) for result in results) else 1


def _payload_ok(payload: dict) -> bool:
    return bool(payload.get("ok"))


def _resolve_max_snapshots(value: int | None) -> int | None:
    if value is not None:
        if value < 0:
            raise ValueError("--max-snapshots 必须大于等于 0")
        return value
    raw = os.environ.get("TRADECAT_CACHE_MAX_SNAPSHOTS")
    if raw is None or not raw.strip():
        return None
    try:
        parsed = int(raw)
    except ValueError as exc:
        raise ValueError("TRADECAT_CACHE_MAX_SNAPSHOTS 必须是整数") from exc
    if parsed < 0:
        raise ValueError("TRADECAT_CACHE_MAX_SNAPSHOTS 必须大于等于 0")
    return parsed


def _should_default_to_tui(argv: list[str]) -> bool:
    if not argv:
        return True
    if "-h" in argv or "--help" in argv:
        return False
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--cache-dir":
            index += 2
            continue
        if token.startswith("--cache-dir="):
            index += 1
            continue
        if token.startswith("-"):
            return False
        return False
    return True


def _should_route_to_tui(argv: list[str]) -> bool:
    if not argv:
        return False
    first = _first_non_global_arg(argv)
    if first is None:
        return False
    if first in {
        "init",
        "doctor",
        "status",
        "path",
        "datasets",
        "config",
        "sync",
        "sync-all",
        "probe",
        "watch",
        "prune",
        "export",
        "analyze",
        "features",
        "tui",
    }:
        return False
    if first in {"-h", "--help"}:
        return False
    return first.startswith("-")


def _first_non_global_arg(argv: list[str]) -> str | None:
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--cache-dir":
            index += 2
            continue
        if token.startswith("--cache-dir="):
            index += 1
            continue
        return token
    return None


def _route_global_tui_args(argv: list[str]) -> list[str]:
    global_args: list[str] = []
    tui_args: list[str] = []
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--cache-dir" and index + 1 < len(argv):
            global_args.extend([token, argv[index + 1]])
            index += 2
            continue
        if token.startswith("--cache-dir="):
            global_args.append(token)
            index += 1
            continue
        tui_args.append(token)
        index += 1
    return [*global_args, "tui", *tui_args]


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


def _pause_after_interactive_fallback(*, enabled: bool, lang: str | None = None) -> None:
    if not enabled:
        return
    if _truthy_env(TUI_NO_PAUSE_ENV):
        return
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return
    try:
        print(f"\n{tr(resolve_lang(lang), 'pause_after_fallback')}", end="", flush=True)
        sys.stdin.readline()
    except (KeyboardInterrupt, OSError):
        print()


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def cache_paths(cache_dir, dataset_key: str | None = None) -> dict:
    if not dataset_key:
        return {
            "cache_dir": str(cache_dir),
            "manifest": str(cache_dir / "manifest.json"),
        }
    dataset = get_dataset(dataset_key)
    dataset_dir = cache_dir / "datasets" / dataset.key
    payload = {
        "cache_dir": str(cache_dir),
        "dataset_key": dataset.key,
        "dataset_dir": str(dataset_dir),
        "manifest": str(dataset_dir / "manifest.json"),
        "latest_json": str(dataset_dir / "latest.json"),
        "latest_jsonl": str(dataset_dir / "latest.jsonl"),
        "latest_csv": str(dataset_dir / "latest.csv"),
        "snapshots_dir": str(dataset_dir / "snapshots"),
    }
    if dataset.is_stream():
        payload["stream_events"] = str(dataset_dir / "stream_events.json")
    return payload


def print_paths(payload: dict) -> None:
    for key, value in payload.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
