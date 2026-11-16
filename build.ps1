# Build everything into dist\
#   dist\FortiVPNManager-Portable-<ver>.exe   single-file portable exe
#   dist\FortiVPNManager\                     folder build (input for the installer)
#   dist\FortiVPNManager-Setup-<ver>.exe      Inno Setup installer
#
#   powershell -ExecutionPolicy Bypass -File build.ps1 [-SkipInstaller]
param([switch]$SkipInstaller)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$version = (Select-String -Path fortivpn_manager\__init__.py -Pattern '__version__ = "(.+)"').Matches[0].Groups[1].Value
Write-Host "Building FortiClient VPN Manager $version" -ForegroundColor Cyan

if (-not (Test-Path .venv)) { python -m venv .venv }
.\.venv\Scripts\python -m pip install -q --upgrade pip
.\.venv\Scripts\python -m pip install -q -r requirements-dev.txt
$running = Get-Process FortiVPNManager -ErrorAction SilentlyContinue
if ($running) { $running | Stop-Process -Force; Start-Sleep -Seconds 2 }
if (Test-Path dist) { Remove-Item dist -Recurse -Force }

# 1) portable single exe
$env:FVM_BUILD = "onefile"
.\.venv\Scripts\pyinstaller --noconfirm --clean --workpath build\onefile FortiVPNManager.spec
if ($LASTEXITCODE) { throw "PyInstaller (onefile) failed" }
Move-Item dist\FortiVPNManager.exe "dist\FortiVPNManager-Portable-$version.exe"

# 2) folder build for the installer
$env:FVM_BUILD = "onedir"
.\.venv\Scripts\pyinstaller --noconfirm --clean --workpath build\onedir FortiVPNManager.spec
if ($LASTEXITCODE) { throw "PyInstaller (onedir) failed" }
Remove-Item Env:FVM_BUILD

# 3) installer
if (-not $SkipInstaller) {
    $iscc = @(
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $iscc) { throw "Inno Setup 6 not found (winget install JRSoftware.InnoSetup)" }
    & $iscc /Q "/DAppVersion=$version" installer\FortiVPNManager.iss
    if ($LASTEXITCODE) { throw "ISCC failed" }
}

Get-ChildItem dist -File | ForEach-Object {
    "{0,-45} {1,8:N1} MB" -f $_.Name, ($_.Length / 1MB)
}
