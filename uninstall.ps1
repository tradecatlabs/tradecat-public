$ErrorActionPreference = "Stop"

$AppDir = if ($env:TRADECAT_INSTALL_DIR) { $env:TRADECAT_INSTALL_DIR } else { Join-Path $env:USERPROFILE ".tradecat\app" }
$BinDir = if ($env:TRADECAT_BIN_DIR) { $env:TRADECAT_BIN_DIR } else { Join-Path $env:USERPROFILE ".local\bin" }
$RuntimeDir = if ($env:TRADECAT_TERMINAL_RUNTIME_DIR) { $env:TRADECAT_TERMINAL_RUNTIME_DIR } else { Join-Path $env:USERPROFILE ".tradecat-terminal\run" }
$KeepCache = if ($env:TRADECAT_KEEP_CACHE) { $env:TRADECAT_KEEP_CACHE } else { "0" }

if ($PSCommandPath -and -not $env:TRADECAT_UNINSTALL_TEMP_RUN) {
    $TempScript = Join-Path $env:TEMP ("tradecat-uninstall-{0}.ps1" -f ([guid]::NewGuid().ToString("N")))
    Copy-Item -Force $PSCommandPath $TempScript
    $env:TRADECAT_UNINSTALL_TEMP_RUN = "1"
    powershell -NoProfile -ExecutionPolicy Bypass -File $TempScript
    $Code = $LASTEXITCODE
    Remove-Item $TempScript -Force -ErrorAction SilentlyContinue
    exit $Code
}

function Log($Message) {
    Write-Host "tradecat-uninstall: $Message"
}

function Backup-Cache-If-Needed {
    $CacheDir = Join-Path $AppDir ".tradecat\cache"
    if ($KeepCache -eq "1" -and (Test-Path $CacheDir)) {
        $BackupDir = Join-Path (Join-Path $env:USERPROFILE ".tradecat") ("cache-backup-{0}" -f (Get-Date -Format "yyyyMMddHHmmss"))
        New-Item -ItemType Directory -Force -Path (Split-Path $BackupDir -Parent) | Out-Null
        Move-Item -Force $CacheDir $BackupDir
        Log "已保留缓存：$BackupDir"
    }
}

function Remove-Launchers {
    foreach ($Name in @("tradecat.cmd", "tcat.cmd", "tradecat-uninstall.cmd", "tcat-uninstall.cmd")) {
        Remove-Item (Join-Path $BinDir $Name) -Force -ErrorAction SilentlyContinue
    }
}

Backup-Cache-If-Needed
Remove-Launchers
Remove-Item $AppDir -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $RuntimeDir -Recurse -Force -ErrorAction SilentlyContinue
Log "已卸载 TradeCat"
Log "已删除安装目录：$AppDir"
Log "已删除命令入口：$(Join-Path $BinDir 'tradecat.cmd'), $(Join-Path $BinDir 'tcat.cmd'), $(Join-Path $BinDir 'tradecat-uninstall.cmd')"
Log "未删除系统 Python、git、uv 或用户 PATH"
