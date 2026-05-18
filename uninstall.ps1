$ErrorActionPreference = "Stop"

$AppDir = if ($env:TRADECAT_INSTALL_DIR) { $env:TRADECAT_INSTALL_DIR } else { Join-Path $env:USERPROFILE ".tradecat\app" }
$BinDir = if ($env:TRADECAT_BIN_DIR) { $env:TRADECAT_BIN_DIR } else { Join-Path $env:USERPROFILE ".local\bin" }
$RuntimeDir = if ($env:TRADECAT_TERMINAL_RUNTIME_DIR) { $env:TRADECAT_TERMINAL_RUNTIME_DIR } else { Join-Path $env:USERPROFILE ".tradecat-terminal\run" }
$KeepCache = if ($env:TRADECAT_KEEP_CACHE) { $env:TRADECAT_KEEP_CACHE } else { "0" }
$ProjectSubdir = if ($env:TRADECAT_PROJECT_SUBDIR) { $env:TRADECAT_PROJECT_SUBDIR } else { "." }

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
    $CacheDir = Join-Path (Join-Path $AppDir $ProjectSubdir) ".tradecat\cache"
    if (-not (Test-Path $CacheDir)) {
        $CacheDir = Join-Path $AppDir ".tradecat\cache"
    }
    if ($KeepCache -eq "1" -and (Test-Path $CacheDir)) {
        $BackupDir = Join-Path (Join-Path $env:USERPROFILE ".tradecat") ("cache-backup-{0}" -f (Get-Date -Format "yyyyMMddHHmmss"))
        New-Item -ItemType Directory -Force -Path (Split-Path $BackupDir -Parent) | Out-Null
        Move-Item -Force $CacheDir $BackupDir
        Log "kept cache backup: $BackupDir"
    }
}

function Remove-Launchers {
    $CurrentCmd = $env:TRADECAT_UNINSTALL_CURRENT_CMD
    foreach ($Name in @("tradecat.cmd", "tcat.cmd", "tradecat.ps1", "tradecat-uninstall.cmd", "tcat-uninstall.cmd")) {
        $Target = Join-Path $BinDir $Name
        if ($CurrentCmd) {
            try {
                if ([System.IO.Path]::GetFullPath($Target) -ieq [System.IO.Path]::GetFullPath($CurrentCmd)) {
                    continue
                }
            } catch {}
        }
        Remove-Item $Target -Force -ErrorAction SilentlyContinue
    }
}

Backup-Cache-If-Needed
Remove-Launchers
Remove-Item $AppDir -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $RuntimeDir -Recurse -Force -ErrorAction SilentlyContinue
Log "TradeCat uninstalled"
Log "removed install dir: $AppDir"
Log "removed command entries: $(Join-Path $BinDir 'tradecat.cmd'), $(Join-Path $BinDir 'tcat.cmd'), $(Join-Path $BinDir 'tradecat-uninstall.cmd')"
Log "system Python, git, uv and user PATH were not removed"
