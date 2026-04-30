from __future__ import annotations

import argparse
import json
import os
import sys

from tradecat_terminal.cache import init_cache, prune_cache, status_cache
from tradecat_terminal.config import load_config
from tradecat_terminal.lifecycle import doctor_local_store, probe_all_datasets, probe_dataset, watch_datasets
from tradecat_terminal.registry import dataset_to_dict, list_datasets
from tradecat_terminal.sync import sync_all_datasets, sync_dataset
from tradecat_terminal.tui import run_tui


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tradecat", description="TradeCat 用户侧终端面板")
    parser.add_argument("--cache-dir", help="本地快照缓存目录，默认 TRADECAT_CACHE_DIR 或 ~/.tradecat/cache")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="初始化本地快照缓存目录")
    init_parser.add_argument("--json", action="store_true", help="输出 JSON")

    doctor_parser = subparsers.add_parser("doctor", help="检查本地缓存状态")
    doctor_parser.add_argument("--json", action="store_true", help="输出 JSON")

    status_parser = subparsers.add_parser("status", help="查看本地缓存状态")
    status_parser.add_argument("--json", action="store_true", help="输出 JSON")

    datasets_parser = subparsers.add_parser("datasets", help="列出可同步 dataset")
    datasets_parser.add_argument("--all", action="store_true", help="包含 inactive dataset")
    datasets_parser.add_argument("--json", action="store_true", help="输出 JSON")

    sync_parser = subparsers.add_parser("sync", help="按 registry 同步一个 dataset 到本地快照缓存")
    sync_parser.add_argument("dataset_key", help="dataset_key，例如 market_snapshot")
    sync_parser.add_argument("--json", action="store_true", help="输出 JSON")

    sync_all_parser = subparsers.add_parser("sync-all", help="同步全部 active dataset 到本地快照缓存")
    sync_all_parser.add_argument("--json", action="store_true", help="输出 JSON")

    probe_parser = subparsers.add_parser("probe", help="探测远端变化；发现变化后写入本地快照缓存")
    probe_parser.add_argument("dataset_key", nargs="?", help="可选 dataset_key；不传则探测全部 active dataset")
    probe_parser.add_argument("--no-write", action="store_true", help="只做 dry-run，不写缓存")
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

    watch_parser = subparsers.add_parser("watch", help="持续探测远端变化并写入本地快照缓存")
    watch_parser.add_argument("dataset_key", nargs="?", help="可选 dataset_key；不传则持续探测全部 active dataset")
    watch_parser.add_argument("--interval", type=float, default=60.0, help="探测间隔秒数")
    watch_parser.add_argument("--max-cycles", type=int, help="最多循环次数；用于测试或一次性运行")
    watch_parser.add_argument("--no-write", action="store_true", help="只持续探测不写缓存")
    watch_parser.add_argument("--json", action="store_true", help="每轮输出 JSON")

    tui_parser = subparsers.add_parser("tui", help="打开终端浏览面板")
    tui_parser.add_argument("dataset_key", nargs="?", help="可选 dataset_key，例如 event_stream")
    tui_parser.add_argument("--limit", type=int, default=0, help="展示行数；0 表示按屏幕高度自动分页")
    tui_parser.add_argument("--plain", action="store_true", help="输出静态文本，不进入交互式 TUI")
    tui_parser.add_argument("--no-live", action="store_true", help="不启动实时探针，只浏览本地缓存")
    tui_parser.add_argument("--probe-interval", type=float, help="实时探针间隔秒数")

    return parser


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    if _should_default_to_tui(raw_argv):
        raw_argv = [*raw_argv, "tui"]
    elif _should_route_to_tui(raw_argv):
        raw_argv = _route_global_tui_args(raw_argv)

    args = build_parser().parse_args(raw_argv)
    config = load_config(args.cache_dir)

    if args.command == "init":
        payload = init_cache(config.cache_dir)
        _print_json_or_text(payload, args.json, f"initialized: cache={config.cache_dir}")
        return 0

    if args.command == "doctor":
        payload = doctor_local_store(config.cache_dir)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
        else:
            print_status(payload)
        return 0 if payload["ok"] else 1

    if args.command == "status":
        payload = status_cache(config.cache_dir)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
        else:
            print_status(payload)
        return 0

    if args.command == "datasets":
        datasets = [dataset_to_dict(dataset) for dataset in list_datasets(include_inactive=args.all)]
        if args.json:
            print(json.dumps(datasets, ensure_ascii=False))
        else:
            print_datasets(datasets)
        return 0

    if args.command == "sync":
        payload = sync_dataset(config.cache_dir, args.dataset_key)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
        else:
            print_sync(payload)
        return 0 if payload.get("ok") else 1

    if args.command == "sync-all":
        results = sync_all_datasets(config.cache_dir)
        if args.json:
            print(json.dumps(results, ensure_ascii=False))
        else:
            for result in results:
                print_sync(result)
        return 0 if all(result.get("ok") for result in results) else 1

    if args.command == "probe":
        if args.dataset_key:
            payload: dict | list = probe_dataset(
                config.cache_dir,
                args.dataset_key,
                write=not args.no_write,
            )
        else:
            payload = probe_all_datasets(config.cache_dir, write=not args.no_write)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
        else:
            print_probe(payload)
        return _payload_exit_code(payload)

    if args.command == "prune":
        payload = prune_cache(
            config.cache_dir,
            dataset_key=args.dataset_key,
            max_snapshots_per_dataset=_resolve_max_snapshots(args.max_snapshots),
            apply=args.apply,
        )
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
        else:
            print_prune(payload)
        return 0 if payload.get("ok") else 1

    if args.command == "watch":
        cycles = watch_datasets(
            config.cache_dir,
            dataset_key=args.dataset_key,
            interval_seconds=args.interval,
            max_cycles=args.max_cycles,
            write=not args.no_write,
        )
        if args.json:
            for results in cycles:
                print(json.dumps(results, ensure_ascii=False))
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
        )
        if output is not None:
            print(output)
        return 0

    return 2


def print_status(payload: dict) -> None:
    print(f"ok: {payload.get('ok')}")
    print(f"cache_dir: {payload.get('cache_dir')}")
    print(f"exists: {payload.get('exists', True)}")
    for dataset in payload.get("datasets", []):
        print(
            "dataset: "
            f"{dataset['dataset_key']} mode={dataset['data_mode']} active={dataset['active']} "
            f"snapshots={dataset['snapshot_count']} events={dataset['event_count']} "
            f"rows={dataset['row_count']} cols={dataset['column_count']} fetched_at={dataset.get('fetched_at')}"
        )
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
        print(f"failed: dataset={payload.get('dataset_key')} error={payload.get('error')}", file=sys.stderr)
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
            print(f"error: {result['error']}", file=sys.stderr)


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


def _print_json_or_text(payload: dict, as_json: bool, text: str) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(text)


def _payload_exit_code(payload: dict | list) -> int:
    results = payload if isinstance(payload, list) else [payload]
    return 0 if all(_payload_ok(result) for result in results) else 1


def _payload_ok(payload: dict) -> bool:
    return bool(payload.get("ok"))


def _resolve_max_snapshots(value: int | None) -> int | None:
    if value is not None:
        return value
    raw = os.environ.get("TRADECAT_CACHE_MAX_SNAPSHOTS")
    if raw is None or not raw.strip():
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise SystemExit("TRADECAT_CACHE_MAX_SNAPSHOTS 必须是整数") from exc


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
    first = argv[0]
    if first in {"init", "doctor", "status", "datasets", "sync", "sync-all", "probe", "watch", "tui"}:
        return False
    if first in {"-h", "--help", "--cache-dir"}:
        return False
    if first.startswith("--cache-dir="):
        return False
    return first.startswith("-")


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


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
