from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

from tradecat_terminal.cache import init_cache, prune_cache, status_cache
from tradecat_terminal.config import load_config
from tradecat_terminal.i18n import LANG_ENV, resolve_lang, tr
from tradecat_terminal.lifecycle import doctor_local_store, probe_all_datasets, probe_dataset, watch_datasets
from tradecat_terminal.registry import dataset_to_dict, get_dataset, list_datasets
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

    export_parser = subparsers.add_parser("export", help="从本地缓存导出当前 dataset 视图")
    export_parser.add_argument("dataset_key", help="dataset_key，例如 event_stream")
    export_parser.add_argument("--format", choices=["json", "jsonl", "csv", "table"], default="json")
    export_parser.add_argument("--limit", type=int, default=0, help="最多导出行数；0 表示不限制")
    export_parser.add_argument("--output", help="输出文件；不传则输出 stdout")
    export_parser.add_argument("--lang", choices=["zh", "en", "ko"], help=f"导出表头显示语言；默认读取 {LANG_ENV} 或配置")

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
    tui_parser.add_argument("--lang", choices=["zh", "en", "ko"], help=f"TUI 语言；默认读取 {LANG_ENV} 或系统 locale")

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

    if args.command == "path":
        payload = cache_paths(config.cache_dir, args.dataset_key)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
        else:
            print_paths(payload)
        return 0

    if args.command == "datasets":
        datasets = [dataset_to_dict(dataset) for dataset in list_datasets(include_inactive=args.all)]
        if args.json:
            print(json.dumps(datasets, ensure_ascii=False))
        else:
            print_datasets(datasets)
        return 0

    if args.command == "config":
        try:
            payload = handle_config_command(args.action, args.key, args.value)
        except ValueError as exc:
            print(f"config error: {exc}", file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
        else:
            print_config(payload)
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

    if args.command == "export":
        payload = export_view(
            config.cache_dir,
            args.dataset_key,
            output_format=args.format,
            limit=args.limit,
            lang=args.lang,
        )
        if args.output:
            Path(args.output).expanduser().write_text(payload, encoding="utf-8")
        else:
            print(payload, end="" if payload.endswith("\n") else "\n")
        return 0

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
        print("单 tap 键：tui_probe_interval.event_stream, tui_fetch_timeout.event_stream")
        return
    print(json.dumps(settings, ensure_ascii=False, indent=2, sort_keys=True))


def export_view(
    cache_dir,
    dataset_key: str,
    *,
    output_format: str,
    limit: int,
    lang: str | None,
) -> str:
    view = build_dataset_view(cache_dir, dataset_key, lang=lang)
    rows = list(view.get("rows") or [])
    if limit > 0:
        rows = rows[:limit]
    if output_format == "json":
        payload = {
            "dataset_key": view.get("dataset_key"),
            "display_name": view.get("display_name"),
            "columns": view.get("columns"),
            "raw_columns": view.get("raw_columns"),
            "meta": view.get("meta"),
            "rows": rows,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
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
