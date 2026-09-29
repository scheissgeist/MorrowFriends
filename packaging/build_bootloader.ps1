# Compile PyInstaller's Windows bootloader from source and install that
# PyInstaller into the build Python. build.ps1 refuses the stock bootloader:
# v0.7.4 shipped with it and was quarantined by Nexus Mods after antivirus hits
# (Microsoft Trojan:Win32/Wacatac.C!ml, Bkav, Zillya, McAfeeD, APEX).
param(
    [string]$Python = ".venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

$pyiVersion = (& $Python -c "import PyInstaller; print(PyInstaller.__version__)" 2>$null)
if (-not $pyiVersion) { $pyiVersion = "6.22.2" }
$work = Join-Path (Get-Location) "build\pyinstaller-src"
New-Item -ItemType Directory -Force -Path $work | Out-Null

& $Python -m pip download "pyinstaller==$pyiVersion" --no-binary :all: --no-deps -d $work -q
if ($LASTEXITCODE -ne 0) { throw "pip download of PyInstaller $pyiVersion source failed" }
$tarball = Join-Path $work "pyinstaller-$pyiVersion.tar.gz"
& $Python -c "import sys, tarfile; tarfile.open(sys.argv[1]).extractall(sys.argv[2])" $tarball $work
if ($LASTEXITCODE -ne 0) { throw "extracting $tarball failed" }
$src = Join-Path $work "pyinstaller-$pyiVersion"

$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$vsPath = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $vsPath) { throw "MSVC x64 build tools not found (install Visual Studio Build Tools, C++ workload)" }
$vcvars = Join-Path $vsPath "VC\Auxiliary\Build\vcvars64.bat"
$pyAbs = (Resolve-Path $Python).Path

Push-Location (Join-Path $src "bootloader")
cmd /c "`"$vcvars`" >nul && `"$pyAbs`" waf distclean all --target-arch=64bit"
$rc = $LASTEXITCODE
Pop-Location
if ($rc -ne 0) { throw "bootloader compile failed" }

& $Python -m pip install --force-reinstall --no-deps $src -q
if ($LASTEXITCODE -ne 0) { throw "installing source-built PyInstaller failed" }
Write-Host "Installed PyInstaller $pyiVersion with a locally compiled bootloader."
