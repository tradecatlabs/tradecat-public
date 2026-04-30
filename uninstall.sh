#!/usr/bin/env sh
set -eu

APP_DIR="${TRADECAT_INSTALL_DIR:-$HOME/.tradecat/app}"
BIN_DIR="${TRADECAT_BIN_DIR:-$HOME/.local/bin}"
RUNTIME_DIR="${TRADECAT_TERMINAL_RUNTIME_DIR:-$HOME/.tradecat-terminal/run}"
KEEP_CACHE="${TRADECAT_KEEP_CACHE:-0}"

log() {
  printf '%s\n' "tradecat-uninstall: $*"
}

backup_cache_if_needed() {
  cache_dir="$APP_DIR/.tradecat/cache"
  if [ "$KEEP_CACHE" = "1" ] && [ -d "$cache_dir" ]; then
    backup_dir="$HOME/.tradecat/cache-backup-$(date +%Y%m%d%H%M%S)"
    mkdir -p "$(dirname "$backup_dir")"
    mv "$cache_dir" "$backup_dir"
    log "已保留缓存：$backup_dir"
  fi
}

remove_launchers() {
  rm -f \
    "$BIN_DIR/tradecat" \
    "$BIN_DIR/tcat" \
    "$BIN_DIR/tradecat-uninstall" \
    "$BIN_DIR/tcat-uninstall"
}

main() {
  backup_cache_if_needed
  remove_launchers
  rm -rf "$APP_DIR"
  rm -rf "$RUNTIME_DIR"
  log "已卸载 TradeCat"
  log "已删除安装目录：$APP_DIR"
  log "已删除命令入口：$BIN_DIR/tradecat, $BIN_DIR/tcat, $BIN_DIR/tradecat-uninstall"
  log "未删除系统 Python、git、uv 或用户 PATH"
}

main "$@"
