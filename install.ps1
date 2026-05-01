$ErrorActionPreference = "Stop"

$RepoUrl = if ($env:TRADECAT_INSTALL_REPO) { $env:TRADECAT_INSTALL_REPO } else { "https://github.com/tukuaiai/tradecat.git" }
$Branch = if ($env:TRADECAT_INSTALL_BRANCH) { $env:TRADECAT_INSTALL_BRANCH } else { "develop" }
$AppDir = if ($env:TRADECAT_INSTALL_DIR) { $env:TRADECAT_INSTALL_DIR } else { Join-Path $env:USERPROFILE ".tradecat\app" }
$BinDir = if ($env:TRADECAT_BIN_DIR) { $env:TRADECAT_BIN_DIR } else { Join-Path $env:USERPROFILE ".local\bin" }
$PythonVersion = if ($env:TRADECAT_PYTHON_VERSION) { $env:TRADECAT_PYTHON_VERSION } else { "3.12" }

function Log($Message) {
    Write-Host "tradecat-install: $Message"
}

function Fail($Message) {
    Write-Error "tradecat-install: ERROR: $Message"
    exit 1
}

function Test-Truthy($Value) {
    return @("1", "true", "yes", "on") -contains ([string]$Value).Trim().ToLowerInvariant()
}

function Test-Command($Name) {
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Invoke-Python($Python, [string[]]$Arguments) {
    if ($Python -eq "py -3.12") {
        & py -3.12 @Arguments
    } else {
        & $Python @Arguments
    }
}

function Test-Python($Python) {
    try {
        if ($Python -eq "py -3.12") {
            & py -3.12 -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= tuple(map(int, '$PythonVersion'.split('.')[:2])) else 1)" *> $null
        } else {
            & $Python -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= tuple(map(int, '$PythonVersion'.split('.')[:2])) else 1)" *> $null
        }
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

function Find-Python {
    foreach ($Candidate in @("py -3.12", "python3.12", "python3", "python")) {
        $Parts = $Candidate.Split(" ")
        $Cmd = $Parts[0]
        if (-not (Test-Command $Cmd)) {
            continue
        }
        if ($Parts.Count -gt 1) {
            $Probe = "$Cmd $($Parts[1])"
        } else {
            $Probe = $Cmd
        }
        if (Test-Python $Probe) {
            return $Probe
        }
    }
    return $null
}

function Ensure-Uv {
    if (Test-Command "uv") {
        return
    }
    Log "未找到 Python $PythonVersion，开始安装 uv，并由 uv 托管 Python"
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    $env:Path = "${env:USERPROFILE}\.local\bin;${env:USERPROFILE}\.cargo\bin;${env:Path}"
    if (-not (Test-Command "uv")) {
        Fail "uv 安装后仍不可用；请重新打开终端或确认用户 PATH"
    }
}

function Checkout-Repo {
    if (-not (Test-Command "git")) {
        Fail "缺少 git；请先安装 Git for Windows"
    }
    New-Item -ItemType Directory -Force -Path (Split-Path $AppDir -Parent) | Out-Null
    if (Test-Path (Join-Path $AppDir ".git")) {
        Log "更新源码：$AppDir"
        git -C $AppDir fetch origin $Branch
        git -C $AppDir checkout $Branch
        git -C $AppDir pull --ff-only origin $Branch
    } elseif (Test-Path $AppDir) {
        Fail "安装目录已存在但不是 Git 仓库：$AppDir；请设置 TRADECAT_INSTALL_DIR 或先移走该目录"
    } else {
        Log "克隆源码：$RepoUrl#$Branch -> $AppDir"
        git clone --branch $Branch --depth 1 $RepoUrl $AppDir
    }
}

function Create-Venv {
    Set-Location $AppDir
    $Python = Find-Python
    if ($Python) {
        Log "使用系统 Python：$Python"
        Invoke-Python $Python @("-m", "venv", ".venv")
        $script:VenvPy = Join-Path $AppDir ".venv\Scripts\python.exe"
        & $script:VenvPy -m pip install -U pip
        & $script:VenvPy -m pip install -e .
    } else {
        Ensure-Uv
        Log "使用 uv 创建 Python $PythonVersion 虚拟环境"
        uv venv --python $PythonVersion .venv
        $script:VenvPy = Join-Path $AppDir ".venv\Scripts\python.exe"
        uv pip install --python $script:VenvPy -e .
    }
    if (-not (Test-Path $script:VenvPy)) {
        Fail "虚拟环境 Python 不存在：$script:VenvPy"
    }
}

function Write-Launcher {
    New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
    $LauncherPs1 = Join-Path $BinDir "tradecat.ps1"
    $UpdaterPs1 = Join-Path $BinDir "tradecat-update.ps1"
    @"
param([switch]`$Force)
`$ErrorActionPreference = "Continue"
`$AppDir = "$AppDir"
`$Branch = "$Branch"
`$VenvPy = "$script:VenvPy"
`$OldHead = ""
try {
    `$OldHead = (git -C `$AppDir rev-parse HEAD 2>`$null)
} catch {
    `$OldHead = ""
}
git -C `$AppDir fetch origin `$Branch *> `$null
`$FetchCode = `$LASTEXITCODE
git -C `$AppDir checkout `$Branch *> `$null
`$CheckoutCode = `$LASTEXITCODE
git -C `$AppDir pull --ff-only origin `$Branch *> `$null
`$PullCode = `$LASTEXITCODE
if (`$FetchCode -ne 0 -or `$CheckoutCode -ne 0 -or `$PullCode -ne 0) {
    if (`$Force) {
        Write-Error "tradecat-update: ERROR: update failed"
        exit 1
    }
    exit 0
}
`$NewHead = ""
try {
    `$NewHead = (git -C `$AppDir rev-parse HEAD 2>`$null)
} catch {
    `$NewHead = ""
}
if (`$OldHead -and `$NewHead -and `$OldHead -ne `$NewHead) {
    & `$VenvPy -m pip install -e `$AppDir *> `$null
    if (`$LASTEXITCODE -ne 0 -and `$Force) {
        Write-Error "tradecat-update: ERROR: dependency refresh failed"
        exit 1
    }
}
"@ | Set-Content -Encoding UTF8 $UpdaterPs1
    @"
`$ErrorActionPreference = "Continue"
`$AppDir = "$AppDir"
`$Branch = "$Branch"
`$VenvPy = "$script:VenvPy"
`$UpdaterPs1 = "$UpdaterPs1"

function Test-Truthy(`$Value) {
    return @("1", "true", "yes", "on") -contains ([string]`$Value).Trim().ToLowerInvariant()
}

function Invoke-TradeCatAutoUpdate {
    if (Test-Truthy `$env:TRADECAT_NO_AUTO_UPDATE) {
        return
    }
    if (-not (Get-Command git -ErrorAction SilentlyContinue) -or -not (Test-Path (Join-Path `$AppDir ".git"))) {
        if (Test-Truthy `$env:TRADECAT_FORCE_UPDATE) {
            Write-Error "tradecat-update: ERROR: cannot update; git or repo is unavailable"
            exit 1
        }
        Write-Warning "tradecat-update: skipped; git or repo is unavailable"
        return
    }
    if (Test-Truthy `$env:TRADECAT_FORCE_UPDATE) {
        & `$UpdaterPs1 -Force
        if (`$LASTEXITCODE -ne 0) {
            exit `$LASTEXITCODE
        }
        return
    }
    `$UpdateInterval = 3600
    try {
        if (`$env:TRADECAT_UPDATE_INTERVAL_SECONDS) {
            `$UpdateInterval = [Math]::Max(0, [int]`$env:TRADECAT_UPDATE_INTERVAL_SECONDS)
        }
    } catch {
        `$UpdateInterval = 3600
    }
    `$UpdateStamp = Join-Path `$AppDir ".tradecat-update-checked-at"
    `$Now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    `$Last = 0
    try {
        if (Test-Path `$UpdateStamp) {
            `$Last = [int64](Get-Content `$UpdateStamp -Raw)
        }
    } catch {
        `$Last = 0
    }
    if (`$UpdateInterval -gt 0 -and `$Last -gt 0 -and (`$Now - `$Last) -lt `$UpdateInterval) {
        return
    }
    try {
        Set-Content -Encoding ASCII -Path `$UpdateStamp -Value ([string]`$Now)
    } catch {}
    Start-Process -FilePath "powershell" -WindowStyle Hidden -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", `$UpdaterPs1) | Out-Null
}

Invoke-TradeCatAutoUpdate
& `$VenvPy -m tradecat_terminal @args
exit `$LASTEXITCODE
"@ | Set-Content -Encoding UTF8 $LauncherPs1
    $Launcher = Join-Path $BinDir "tradecat.cmd"
    "@echo off`r`npowershell -NoProfile -ExecutionPolicy Bypass -File `"$LauncherPs1`" %*`r`n" | Set-Content -Encoding ASCII $Launcher
    $ShortLauncher = Join-Path $BinDir "tcat.cmd"
    "@echo off`r`npowershell -NoProfile -ExecutionPolicy Bypass -File `"$LauncherPs1`" %*`r`n" | Set-Content -Encoding ASCII $ShortLauncher
    $UninstallLauncher = Join-Path $BinDir "tradecat-uninstall.cmd"
    "@echo off`r`nset `"TRADECAT_INSTALL_DIR=$AppDir`"`r`nset `"TRADECAT_BIN_DIR=$BinDir`"`r`npowershell -NoProfile -ExecutionPolicy Bypass -File `"$AppDir\uninstall.ps1`" %*`r`n" | Set-Content -Encoding ASCII $UninstallLauncher
    $ShortUninstallLauncher = Join-Path $BinDir "tcat-uninstall.cmd"
    "@echo off`r`nset `"TRADECAT_INSTALL_DIR=$AppDir`"`r`nset `"TRADECAT_BIN_DIR=$BinDir`"`r`npowershell -NoProfile -ExecutionPolicy Bypass -File `"$AppDir\uninstall.ps1`" %*`r`n" | Set-Content -Encoding ASCII $ShortUninstallLauncher
    if (-not (Test-Truthy $env:TRADECAT_INSTALL_SKIP_PATH_WRITE)) {
        $UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
        if (-not ($UserPath.Split(";") -contains $BinDir)) {
            [Environment]::SetEnvironmentVariable("Path", "$BinDir;$UserPath", "User")
        }
        $env:Path = "$BinDir;$env:Path"
    } else {
        Log "按配置跳过写入用户 PATH"
    }
}

function Bootstrap-Cache {
    $OldNoAutoUpdate = $env:TRADECAT_NO_AUTO_UPDATE
    $env:TRADECAT_NO_AUTO_UPDATE = "1"
    & (Join-Path $BinDir "tradecat.cmd") init | Out-Null
    if (Test-Truthy $env:TRADECAT_INSTALL_SKIP_SYNC) {
        Log "已初始化本地缓存目录；按配置跳过初次公开数据同步"
        $env:TRADECAT_NO_AUTO_UPDATE = $OldNoAutoUpdate
        return
    }
    try {
        & (Join-Path $BinDir "tradecat.cmd") sync-all | Out-Null
        Log "已同步公开数据到本地缓存"
    } catch {
        Log "公开数据初次同步失败；安装已完成，首次运行 tradecat 时会继续探测"
    } finally {
        $env:TRADECAT_NO_AUTO_UPDATE = $OldNoAutoUpdate
    }
}

Checkout-Repo
Create-Venv
Write-Launcher
Bootstrap-Cache
Log "安装完成"
Log "命令入口：$(Join-Path $BinDir 'tradecat.cmd')"
Log "卸载命令：$(Join-Path $BinDir 'tradecat-uninstall.cmd')"
if (Test-Truthy $env:TRADECAT_INSTALL_SKIP_PATH_WRITE) {
    Log "启动：$(Join-Path $BinDir 'tradecat.cmd')"
} else {
    Log "启动：tradecat"
}
