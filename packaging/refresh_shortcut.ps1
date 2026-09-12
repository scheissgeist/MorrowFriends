# Rebuild icon, re-point Desktop shortcut at the .ico (bypasses exe icon cache), flush shell cache.
$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root

python packaging/make_icon.py
if ($LASTEXITCODE -ne 0) { throw "icon failed" }

python -m PyInstaller packaging/morrowfriends.spec --noconfirm
if ($LASTEXITCODE -ne 0) { throw "build failed" }

$exe = Join-Path $Root "dist\MorrowFriends.exe"
$ico = Join-Path $Root "packaging\morrowfriends.ico"
$desktop = [Environment]::GetFolderPath("Desktop")

# Fresh shortcut name forces Explorer to drop the cached glyph
$old = Join-Path $desktop "MorrowFriends.lnk"
$new = Join-Path $desktop "MorrowFriends.lnk"
if (Test-Path $old) { Remove-Item $old -Force }

$wsh = New-Object -ComObject WScript.Shell
$sc = $wsh.CreateShortcut($new)
$sc.TargetPath = $exe
$sc.WorkingDirectory = Split-Path $exe -Parent
$sc.Description = "MorrowFriends launcher"
# Point at the ICO file directly — more reliable than exe,0 for shell thumbs
$sc.IconLocation = "$ico,0"
$sc.Save()

# Flush Windows icon cache (Win10/11)
$ie4 = Join-Path $env:SystemRoot "System32\ie4uinit.exe"
if (Test-Path $ie4) {
    & $ie4 -show 2>$null
    & $ie4 -ClearIconCache 2>$null
}

# Nudge Explorer
Stop-Process -Name explorer -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 800
Start-Process explorer

Write-Host "Shortcut refreshed -> $new"
Write-Host "Icon file: $ico"
Write-Host "If it still looks wrong: right-click Desktop -> Refresh, or sign out/in."
