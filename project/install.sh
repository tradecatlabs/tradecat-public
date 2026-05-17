#!/usr/bin/env sh
set -eu

REPO_URL="${TRADECAT_INSTALL_REPO:-https://github.com/tukuaiai/tradecat.git}"
DEFAULT_REF="${TRADECAT_INSTALL_DEFAULT_REF:-v0.1.3}"
BRANCH="${TRADECAT_INSTALL_BRANCH:-develop}"
PINNED_REF=1
if [ -n "${TRADECAT_INSTALL_REF:-}" ]; then
  REF="$TRADECAT_INSTALL_REF"
elif [ -n "${TRADECAT_INSTALL_BRANCH:-}" ]; then
  REF="$BRANCH"
  PINNED_REF=0
else
  REF="$DEFAULT_REF"
fi
APP_DIR="${TRADECAT_INSTALL_DIR:-$HOME/.tradecat/app}"
BIN_DIR="${TRADECAT_BIN_DIR:-$HOME/.local/bin}"
PYTHON_VERSION="${TRADECAT_PYTHON_VERSION:-3.12}"
PROJECT_SUBDIR="${TRADECAT_PROJECT_SUBDIR:-project}"

log() {
  printf '%s\n' "tradecat-install: $*"
}

fail() {
  printf '%s\n' "tradecat-install: ERROR: $*" >&2
  exit 1
}

truthy() {
  case "$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]')" in
    1|true|yes|on) return 0 ;;
    *) return 1 ;;
  esac
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "缺少命令：$1"
}

python_ok() {
  "$1" - "$PYTHON_VERSION" <<'PY' >/dev/null 2>&1
import sys
want = tuple(int(part) for part in sys.argv[1].split(".")[:2])
raise SystemExit(0 if sys.version_info[:2] >= want else 1)
PY
}

find_python() {
  for candidate in python3.12 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 && python_ok "$candidate"; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

ensure_uv() {
  if command -v uv >/dev/null 2>&1; then
    return 0
  fi
  if ! truthy "${TRADECAT_INSTALL_ALLOW_UV_BOOTSTRAP:-}"; then
    fail "未找到 Python $PYTHON_VERSION 或 uv。出于供应链安全，安装器不会静默执行远程 uv 安装脚本；请先安装 Python $PYTHON_VERSION+，或设置 TRADECAT_INSTALL_ALLOW_UV_BOOTSTRAP=1 明确允许安装器引导 uv。"
  fi
  need_cmd curl
  log "按 TRADECAT_INSTALL_ALLOW_UV_BOOTSTRAP=1 明确授权安装 uv，并由 uv 托管 Python"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  export PATH
  command -v uv >/dev/null 2>&1 || fail "uv 安装后仍不可用；请确认 ~/.local/bin 或 ~/.cargo/bin 已加入 PATH"
}

checkout_repo() {
  need_cmd git
  mkdir -p "$(dirname "$APP_DIR")"
  if [ -d "$APP_DIR/.git" ]; then
    log "更新源码：$APP_DIR"
    fetch_ref
    git -C "$APP_DIR" checkout "$REF"
    if [ "$PINNED_REF" -eq 0 ]; then
      git -C "$APP_DIR" pull --ff-only origin "$REF"
    fi
  elif [ -e "$APP_DIR" ]; then
    fail "安装目录已存在但不是 Git 仓库：$APP_DIR；请设置 TRADECAT_INSTALL_DIR 或先移走该目录"
  else
    log "克隆源码：$REPO_URL#$REF -> $APP_DIR"
    git clone --branch "$REF" --depth 1 "$REPO_URL" "$APP_DIR"
  fi
}

fetch_ref() {
  git -C "$APP_DIR" fetch origin "$REF" ||
    git -C "$APP_DIR" fetch origin "refs/tags/$REF:refs/tags/$REF"
}

resolve_project_dir() {
  project_dir="$APP_DIR/$PROJECT_SUBDIR"
  if [ -f "$project_dir/pyproject.toml" ]; then
    printf '%s\n' "$project_dir"
    return 0
  fi
  if [ -f "$APP_DIR/pyproject.toml" ]; then
    printf '%s\n' "$APP_DIR"
    return 0
  fi
  fail "未找到 TradeCat 项目 pyproject.toml：$project_dir"
}

create_venv() {
  PROJECT_DIR="$(resolve_project_dir)"
  cd "$PROJECT_DIR"
  if PYTHON_BIN="$(find_python)"; then
    log "使用系统 Python：$($PYTHON_BIN --version 2>&1)"
    "$PYTHON_BIN" -m venv .venv
    VENV_PY="$PROJECT_DIR/.venv/bin/python"
    if [ ! -x "$VENV_PY" ] && [ -x "$PROJECT_DIR/.venv/Scripts/python.exe" ]; then
      VENV_PY="$PROJECT_DIR/.venv/Scripts/python.exe"
    fi
    "$VENV_PY" -m pip install -U pip
    if [ -f "$PROJECT_DIR/constraints.txt" ]; then
      "$VENV_PY" -m pip install -c "$PROJECT_DIR/constraints.txt" -e .
    else
      "$VENV_PY" -m pip install -e .
    fi
  else
    ensure_uv
    log "使用 uv 创建 Python $PYTHON_VERSION 虚拟环境"
    uv venv --python "$PYTHON_VERSION" .venv
    if [ -x "$PROJECT_DIR/.venv/bin/python" ]; then
      VENV_PY="$PROJECT_DIR/.venv/bin/python"
    else
      VENV_PY="$PROJECT_DIR/.venv/Scripts/python.exe"
    fi
    if [ -f "$PROJECT_DIR/constraints.txt" ]; then
      uv pip install --python "$VENV_PY" -c "$PROJECT_DIR/constraints.txt" -e .
    else
      uv pip install --python "$VENV_PY" -e .
    fi
  fi
  [ -x "$VENV_PY" ] || fail "虚拟环境 Python 不存在：$VENV_PY"
}

write_launcher() {
  PROJECT_DIR="$(resolve_project_dir)"
  write_executable "$BIN_DIR/tradecat" <<EOF
#!/usr/bin/env sh
APP_DIR="$APP_DIR"
PROJECT_DIR="$PROJECT_DIR"
BRANCH="$BRANCH"
REF="$REF"
PINNED_REF="$PINNED_REF"
VENV_PY="$VENV_PY"

truthy() {
  case "\$(printf '%s' "\${1:-}" | tr '[:upper:]' '[:lower:]')" in
    1|true|yes|on) return 0 ;;
    *) return 1 ;;
  esac
}

auto_update() {
  if [ "\$PINNED_REF" = "1" ]; then
    return 0
  fi
  if truthy "\${TRADECAT_NO_AUTO_UPDATE:-}"; then
    return 0
  fi
  if ! command -v git >/dev/null 2>&1 || [ ! -d "\$APP_DIR/.git" ]; then
    if truthy "\${TRADECAT_FORCE_UPDATE:-}"; then
      printf '%s\n' "tradecat-update: ERROR: cannot update; git or repo is unavailable" >&2
      exit 1
    fi
    printf '%s\n' "tradecat-update: skipped; git or repo is unavailable" >&2
    return 0
  fi
  update_stamp="\$APP_DIR/.tradecat-update-checked-at"
  update_interval="\${TRADECAT_UPDATE_INTERVAL_SECONDS:-3600}"
  now="\$(date +%s 2>/dev/null || printf '0')"
  last="0"
  if [ -f "\$update_stamp" ]; then
    last="\$(cat "\$update_stamp" 2>/dev/null || printf '0')"
  fi
  case "\$update_interval" in
    ''|*[!0-9]*) update_interval=3600 ;;
  esac
  case "\$last" in
    ''|*[!0-9]*) last=0 ;;
  esac
  if truthy "\${TRADECAT_FORCE_UPDATE:-}"; then
    run_update_blocking
    return 0
  fi
  if [ "\$now" -gt 0 ] && [ "\$last" -gt 0 ] && [ \$((now - last)) -lt "\$update_interval" ]; then
    return 0
  fi
  printf '%s\n' "\$now" >"\$update_stamp" 2>/dev/null || true
  (run_update_blocking >/dev/null 2>&1 || true) &
}

run_update_blocking() {
  old_head="\$(git -C "\$APP_DIR" rev-parse HEAD 2>/dev/null || true)"
  if git -C "\$APP_DIR" fetch origin "\$REF" >/dev/null 2>&1 &&
     git -C "\$APP_DIR" checkout "\$REF" >/dev/null 2>&1 &&
     git -C "\$APP_DIR" pull --ff-only origin "\$REF" >/dev/null 2>&1; then
    new_head="\$(git -C "\$APP_DIR" rev-parse HEAD 2>/dev/null || true)"
    if [ -n "\$old_head" ] && [ -n "\$new_head" ] && [ "\$old_head" != "\$new_head" ]; then
      if "\$VENV_PY" -m pip install -e "\$PROJECT_DIR" >/dev/null 2>&1; then
        printf '%s\n' "tradecat-update: updated to latest" >&2
      elif truthy "\${TRADECAT_FORCE_UPDATE:-}"; then
        printf '%s\n' "tradecat-update: ERROR: dependency refresh failed" >&2
        exit 1
      else
        printf '%s\n' "tradecat-update: dependency refresh failed; continuing with local version" >&2
      fi
    fi
  elif truthy "\${TRADECAT_FORCE_UPDATE:-}"; then
    printf '%s\n' "tradecat-update: ERROR: update failed" >&2
    exit 1
  else
    printf '%s\n' "tradecat-update: update failed; continuing with local version" >&2
  fi
}

auto_update
exec "$VENV_PY" -m tradecat_terminal "\$@"
EOF
  write_executable "$BIN_DIR/tcat" <<EOF
#!/usr/bin/env sh
exec "$BIN_DIR/tradecat" "\$@"
EOF
  write_executable "$BIN_DIR/tradecat-uninstall" <<EOF
#!/usr/bin/env sh
TRADECAT_INSTALL_DIR="$APP_DIR" TRADECAT_BIN_DIR="$BIN_DIR" exec sh "$PROJECT_DIR/uninstall.sh" "\$@"
EOF
  write_executable "$BIN_DIR/tcat-uninstall" <<EOF
#!/usr/bin/env sh
TRADECAT_INSTALL_DIR="$APP_DIR" TRADECAT_BIN_DIR="$BIN_DIR" exec sh "$PROJECT_DIR/uninstall.sh" "\$@"
EOF
}

write_executable() {
  target="$1"
  target_dir="$(dirname "$target")"
  tmp_file="$(mktemp "${TMPDIR:-/tmp}/tradecat-launcher.XXXXXX")" || fail "无法创建临时 launcher 文件"
  cat >"$tmp_file" || {
    rm -f "$tmp_file"
    fail "无法写入临时 launcher 文件"
  }
  chmod 0755 "$tmp_file" || {
    rm -f "$tmp_file"
    fail "无法设置 launcher 可执行权限：$target"
  }
  mkdir -p "$target_dir" || {
    rm -f "$tmp_file"
    fail "无法创建命令目录：$target_dir"
  }
  rm -f "$target" || {
    rm -f "$tmp_file"
    fail "无法替换旧命令入口：$target"
  }
  mv "$tmp_file" "$target" || {
    rm -f "$tmp_file"
    fail "无法安装命令入口：$target"
  }
}

ensure_shell_path() {
  if truthy "${TRADECAT_INSTALL_SKIP_PATH_WRITE:-}"; then
    log "按配置跳过写入 shell profile"
    return 0
  fi
  path_line="export PATH=\"$BIN_DIR:\$PATH\""
  wrote=0
  for profile in "$HOME/.profile" "$HOME/.bashrc" "$HOME/.zshrc"; do
    if [ -e "$profile" ] && ! grep -F "$BIN_DIR" "$profile" >/dev/null 2>&1; then
      {
        printf '\n'
        printf '# Added by TradeCat installer\n'
        printf '%s\n' "$path_line"
      } >>"$profile"
      wrote=1
    fi
  done
  if [ ! -e "$HOME/.profile" ]; then
    {
      printf '# Added by TradeCat installer\n'
      printf '%s\n' "$path_line"
    } >"$HOME/.profile"
    wrote=1
  fi
  if [ "$wrote" = "1" ]; then
    log "已把 $BIN_DIR 写入 shell profile；重新登录或新开终端后可直接运行 tradecat"
  fi
}

bootstrap_cache() {
  TRADECAT_NO_AUTO_UPDATE=1 "$BIN_DIR/tradecat" init >/dev/null
  if truthy "${TRADECAT_INSTALL_SKIP_SYNC:-}"; then
    log "已初始化本地缓存目录；按配置跳过初次公开数据同步"
    return 0
  fi
  if TRADECAT_NO_AUTO_UPDATE=1 "$BIN_DIR/tradecat" sync-all >/dev/null 2>&1; then
    log "已同步公开数据到本地缓存"
  else
    log "公开数据全量初次同步失败；开始兜底同步默认事件流"
    if TRADECAT_NO_AUTO_UPDATE=1 "$BIN_DIR/tradecat" sync event_stream >/dev/null 2>&1; then
      log "已同步默认事件流缓存；其它 tap 可稍后执行 tradecat sync-all 补齐"
    else
      log "默认事件流兜底同步也失败；安装已完成，首次运行 tradecat 时会继续探测"
      log "弱网可执行：tradecat config set tui_fetch_timeout.event_stream 3 && tradecat sync-all"
    fi
  fi
}

main() {
  checkout_repo
  create_venv
  write_launcher
  ensure_shell_path
  bootstrap_cache

  log "安装完成"
  log "命令入口：${BIN_DIR}/tradecat"
  log "卸载命令：${BIN_DIR}/tradecat-uninstall"
  if ! printf '%s' ":$PATH:" | grep -F ":$BIN_DIR:" >/dev/null 2>&1; then
    log "当前会话 PATH 未包含 ${BIN_DIR}；立即运行可用：${BIN_DIR}/tradecat"
    log "或执行：export PATH=\"${BIN_DIR}:\$PATH\""
  fi
  log "启动：${BIN_DIR}/tradecat"
}

main "$@"
