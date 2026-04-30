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
        Invoke-Python $Python @("-c", "import sys; raise SystemExit(0 if sys.version_info[:2] >= tuple(map(int, '$PythonVersion'.split('.')[:2])) else 1)") | Out-Null
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
    $env:Path = "$env:USERPROFILE\.local\bin;$env:USERPROFILE\.cargo\bin;$env:Path"
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
    $Launcher = Join-Path $BinDir "tradecat.cmd"
    "@echo off`r`n`"$script:VenvPy`" -m tradecat_terminal %*`r`n" | Set-Content -Encoding ASCII $Launcher
    $ShortLauncher = Join-Path $BinDir "tcat.cmd"
    "@echo off`r`n`"$script:VenvPy`" -m tradecat_terminal %*`r`n" | Set-Content -Encoding ASCII $ShortLauncher
    $UninstallLauncher = Join-Path $BinDir "tradecat-uninstall.cmd"
    "@echo off`r`nset `"TRADECAT_INSTALL_DIR=$AppDir`"`r`nset `"TRADECAT_BIN_DIR=$BinDir`"`r`npowershell -NoProfile -ExecutionPolicy Bypass -File `"$AppDir\uninstall.ps1`" %*`r`n" | Set-Content -Encoding ASCII $UninstallLauncher
    $ShortUninstallLauncher = Join-Path $BinDir "tcat-uninstall.cmd"
    "@echo off`r`nset `"TRADECAT_INSTALL_DIR=$AppDir`"`r`nset `"TRADECAT_BIN_DIR=$BinDir`"`r`npowershell -NoProfile -ExecutionPolicy Bypass -File `"$AppDir\uninstall.ps1`" %*`r`n" | Set-Content -Encoding ASCII $ShortUninstallLauncher
    $UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if (-not ($UserPath.Split(";") -contains $BinDir)) {
        [Environment]::SetEnvironmentVariable("Path", "$BinDir;$UserPath", "User")
    }
    $env:Path = "$BinDir;$env:Path"
}

function Bootstrap-Cache {
    & (Join-Path $BinDir "tradecat.cmd") init | Out-Null
    try {
        & (Join-Path $BinDir "tradecat.cmd") sync-all | Out-Null
        Log "已同步公开数据到本地缓存"
    } catch {
        Log "公开数据初次同步失败；安装已完成，首次运行 tradecat 时会继续探测"
    }
}

Checkout-Repo
Create-Venv
Write-Launcher
Bootstrap-Cache
Log "安装完成"
Log "命令入口：$(Join-Path $BinDir 'tradecat.cmd')"
Log "卸载命令：$(Join-Path $BinDir 'tradecat-uninstall.cmd')"
Log "启动：tradecat"
