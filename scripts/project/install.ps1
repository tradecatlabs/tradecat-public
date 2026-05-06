$ErrorActionPreference = "Stop"

$RepoUrl = if ($env:TRADECAT_INSTALL_REPO) { $env:TRADECAT_INSTALL_REPO } else { "https://github.com/tukuaiai/tradecat.git" }
$Branch = if ($env:TRADECAT_INSTALL_BRANCH) { $env:TRADECAT_INSTALL_BRANCH } else { "develop" }
$AppDir = if ($env:TRADECAT_INSTALL_DIR) { $env:TRADECAT_INSTALL_DIR } else { Join-Path $env:USERPROFILE ".tradecat\app" }
$BinDir = if ($env:TRADECAT_BIN_DIR) { $env:TRADECAT_BIN_DIR } else { Join-Path $env:USERPROFILE ".local\bin" }
$PythonVersion = if ($env:TRADECAT_PYTHON_VERSION) { $env:TRADECAT_PYTHON_VERSION } else { "3.12" }
$ProjectSubdir = if ($env:TRADECAT_PROJECT_SUBDIR) { $env:TRADECAT_PROJECT_SUBDIR } else { "scripts\project" }

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
    Log "Python $PythonVersion not found; installing uv-managed Python"
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    $UserLocalBin = Join-Path (Join-Path $env:USERPROFILE ".local") "bin"
    $UserCargoBin = Join-Path (Join-Path $env:USERPROFILE ".cargo") "bin"
    $env:Path = @($UserLocalBin, $UserCargoBin, $env:Path) -join ";"
    if (-not (Test-Command "uv")) {
        Fail "uv is still unavailable after installation; reopen the terminal or check user PATH"
    }
}

function Checkout-Repo {
    if (-not (Test-Command "git")) {
        Fail "git is missing; install Git for Windows first"
    }
    New-Item -ItemType Directory -Force -Path (Split-Path $AppDir -Parent) | Out-Null
    if (Test-Path (Join-Path $AppDir ".git")) {
        Log "updating source: $AppDir"
        git -C $AppDir fetch origin $Branch
        git -C $AppDir checkout $Branch
        git -C $AppDir pull --ff-only origin $Branch
    } elseif (Test-Path $AppDir) {
        Fail "install dir exists but is not a Git repository: $AppDir; set TRADECAT_INSTALL_DIR or move it away"
    } else {
        Log "cloning source: $RepoUrl#$Branch -> $AppDir"
        git clone --branch $Branch --depth 1 $RepoUrl $AppDir
    }
}

function Resolve-ProjectDir {
    $ProjectDir = Join-Path $AppDir $ProjectSubdir
    if (Test-Path (Join-Path $ProjectDir "pyproject.toml")) {
        return $ProjectDir
    }
    if (Test-Path (Join-Path $AppDir "pyproject.toml")) {
        return $AppDir
    }
    Fail "TradeCat pyproject.toml not found: $ProjectDir"
}

function Create-Venv {
    $script:ProjectDir = Resolve-ProjectDir
    Set-Location $script:ProjectDir
    $Python = Find-Python
    if ($Python) {
        Log "using system Python: $Python"
        Invoke-Python $Python @("-m", "venv", ".venv")
        $script:VenvPy = Join-Path $script:ProjectDir ".venv\Scripts\python.exe"
        & $script:VenvPy -m pip install -U pip
        & $script:VenvPy -m pip install -e .
    } else {
        Ensure-Uv
        Log "creating Python $PythonVersion virtualenv with uv"
        uv venv --python $PythonVersion .venv
        $script:VenvPy = Join-Path $script:ProjectDir ".venv\Scripts\python.exe"
        uv pip install --python $script:VenvPy -e .
    }
    if (-not (Test-Path $script:VenvPy)) {
        Fail "virtualenv Python not found: $script:VenvPy"
    }
}

function Write-Launcher {
    if (-not $script:ProjectDir) {
        $script:ProjectDir = Resolve-ProjectDir
    }
    New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
    $LauncherPs1 = Join-Path $BinDir "tradecat.ps1"
    $UpdaterPs1 = Join-Path $BinDir "tradecat-update.ps1"
    @"
param([switch]`$Force)
`$ErrorActionPreference = "Continue"
`$AppDir = "$AppDir"
`$ProjectDir = "$script:ProjectDir"
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
    & `$VenvPy -m pip install -e `$ProjectDir *> `$null
    if (`$LASTEXITCODE -ne 0 -and `$Force) {
        Write-Error "tradecat-update: ERROR: dependency refresh failed"
        exit 1
    }
}
"@ | Set-Content -Encoding UTF8 $UpdaterPs1
    @"
`$ErrorActionPreference = "Continue"
`$AppDir = "$AppDir"
`$ProjectDir = "$script:ProjectDir"
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
    "@echo off`r`nset `"TRADECAT_INSTALL_DIR=$AppDir`"`r`nset `"TRADECAT_BIN_DIR=$BinDir`"`r`nset `"TRADECAT_UNINSTALL_CURRENT_CMD=%~f0`"`r`npowershell -NoProfile -ExecutionPolicy Bypass -File `"$script:ProjectDir\uninstall.ps1`" %*`r`nset `"_TC_CODE=%ERRORLEVEL%`"`r`nstart `"`" /b powershell -NoProfile -WindowStyle Hidden -Command `"Start-Sleep -Seconds 1; Remove-Item -LiteralPath '%~f0' -Force -ErrorAction SilentlyContinue`" >nul 2>nul`r`nexit /b %_TC_CODE%`r`n" | Set-Content -Encoding ASCII $UninstallLauncher
    $ShortUninstallLauncher = Join-Path $BinDir "tcat-uninstall.cmd"
    "@echo off`r`nset `"TRADECAT_INSTALL_DIR=$AppDir`"`r`nset `"TRADECAT_BIN_DIR=$BinDir`"`r`nset `"TRADECAT_UNINSTALL_CURRENT_CMD=%~f0`"`r`npowershell -NoProfile -ExecutionPolicy Bypass -File `"$script:ProjectDir\uninstall.ps1`" %*`r`nset `"_TC_CODE=%ERRORLEVEL%`"`r`nstart `"`" /b powershell -NoProfile -WindowStyle Hidden -Command `"Start-Sleep -Seconds 1; Remove-Item -LiteralPath '%~f0' -Force -ErrorAction SilentlyContinue`" >nul 2>nul`r`nexit /b %_TC_CODE%`r`n" | Set-Content -Encoding ASCII $ShortUninstallLauncher
    if (-not (Test-Truthy $env:TRADECAT_INSTALL_SKIP_PATH_WRITE)) {
        $UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
        if (-not ($UserPath.Split(";") -contains $BinDir)) {
            [Environment]::SetEnvironmentVariable("Path", "$BinDir;$UserPath", "User")
        }
        $env:Path = "$BinDir;$env:Path"
    } else {
        Log "skipping user PATH write by configuration"
    }
}

function Bootstrap-Cache {
    $OldNoAutoUpdate = $env:TRADECAT_NO_AUTO_UPDATE
    $env:TRADECAT_NO_AUTO_UPDATE = "1"
    & (Join-Path $BinDir "tradecat.cmd") init | Out-Null
    if (Test-Truthy $env:TRADECAT_INSTALL_SKIP_SYNC) {
        Log "initialized local cache; skipped initial public data sync by configuration"
        $env:TRADECAT_NO_AUTO_UPDATE = $OldNoAutoUpdate
        return
    }
    try {
        & (Join-Path $BinDir "tradecat.cmd") sync-all | Out-Null
        Log "synced public data to local cache"
    } catch {
        Log "initial public data sync failed; installation is complete and tradecat will keep probing on first run"
    } finally {
        $env:TRADECAT_NO_AUTO_UPDATE = $OldNoAutoUpdate
    }
}

Checkout-Repo
Create-Venv
Write-Launcher
Bootstrap-Cache
Log "installation complete"
Log "command entry: $(Join-Path $BinDir 'tradecat.cmd')"
Log "uninstall command: $(Join-Path $BinDir 'tradecat-uninstall.cmd')"
if (Test-Truthy $env:TRADECAT_INSTALL_SKIP_PATH_WRITE) {
    Log "start: $(Join-Path $BinDir 'tradecat.cmd')"
} else {
    Log "start: tradecat"
}
