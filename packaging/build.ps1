# Build friend-ready MorrowFriends (one-folder app + versioned ZIP)
param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

& $Python -m pip install -r requirements.txt -q
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

# Refuse PyInstaller's prebuilt bootloader. v0.7.4 used it and was quarantined
# by Nexus Mods after antivirus hits; run packaging/build_bootloader.ps1 first.
$stockCheck = @'
import hashlib, os, sys
import PyInstaller
p = os.path.join(os.path.dirname(PyInstaller.__file__), "bootloader", "Windows-64bit-intel", "runw.exe")
h = hashlib.sha256(open(p, "rb").read()).hexdigest()
# runw.exe from the PyPI win_amd64 wheel; add a line per PyInstaller upgrade.
stock = {"87b0c589906a5d690c26c602bf2ee7e43b3eab55574bf72887a8ca07fbb2dba0"}  # 6.22.2
print(h)
sys.exit(1 if h in stock else 0)
'@
$bootHash = $stockCheck | & $Python -
if ($LASTEXITCODE -ne 0) { throw "Stock PyInstaller bootloader ($bootHash). Run: powershell -File packaging/build_bootloader.ps1 -Python $Python" }

& $Python packaging/make_icon.py
if ($LASTEXITCODE -ne 0) { throw "icon generation failed" }
$env:MF_ONEDIR = "1"
# Keep the Python archive out of the exe (MorrowFriends.pkg beside it). VT 2026-09-29:
# overlay exe 2/71, bare-bootloader exe 1/69 (Microsoft Wacatac.B!ml only).
$env:MF_APPEND_PKG = "0"
& $Python -m PyInstaller packaging/morrowfriends.spec --noconfirm
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$appDir = Join-Path (Get-Location) "dist\MorrowFriends"
$exe = Join-Path $appDir "MorrowFriends.exe"
$ico = Join-Path (Get-Location) "packaging\morrowfriends.ico"
$voiceJson = Join-Path (Get-Location) "packaging\MorrowFriends.voice.json"
$startHere = Join-Path (Get-Location) "packaging\START HERE - MorrowFriends.txt"
$releaseDocs = @(
    (Join-Path (Get-Location) "LICENSE"),
    (Join-Path (Get-Location) "PRIVACY.md"),
    (Join-Path (Get-Location) "THIRD_PARTY_NOTICES.md")
)
if (-not (Test-Path $exe)) { throw "Build failed: $exe missing" }
if (Test-Path $voiceJson) {
    Copy-Item $voiceJson (Join-Path $appDir "MorrowFriends.voice.json") -Force
}
if (Test-Path $startHere) {
    Copy-Item $startHere (Join-Path $appDir "START HERE - MorrowFriends.txt") -Force
}
foreach ($doc in $releaseDocs) {
    if (Test-Path $doc) {
        Copy-Item $doc (Join-Path $appDir (Split-Path $doc -Leaf)) -Force
    }
}

$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop "MorrowFriends.lnk"
if (Test-Path $shortcutPath) { Remove-Item $shortcutPath -Force }
$wsh = New-Object -ComObject WScript.Shell
$sc = $wsh.CreateShortcut($shortcutPath)
$sc.TargetPath = $exe
$sc.WorkingDirectory = $appDir
$sc.Description = "MorrowFriends launcher - Host or Join"
# Use .ico path so Explorer does not stick on a stale exe icon cache entry
$sc.IconLocation = "$ico,0"
$sc.Save()

# Remove old-branded shortcut if present
$oldShortcut = Join-Path $desktop "Morrowind Friends.lnk"
if (Test-Path $oldShortcut) { Remove-Item $oldShortcut -Force }

$pfx = $env:MORROWFRIENDS_PFX
if (-not $pfx) {
    $defaultPfx = Join-Path (Get-Location) "packaging\morrowfriends.pfx"
    if (Test-Path $defaultPfx) { $pfx = $defaultPfx }
}
$signed = $false
if ($pfx -and (Test-Path $pfx)) {
    $signtool = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($signtool) {
        $signArgs = @("sign", "/fd", "SHA256", "/td", "SHA256", "/tr", "http://timestamp.digicert.com", "/f", $pfx, $exe)
        if ($env:MORROWFRIENDS_PFX_PASSWORD) {
            $signArgs = @("sign", "/fd", "SHA256", "/td", "SHA256", "/tr", "http://timestamp.digicert.com", "/f", $pfx, "/p", $env:MORROWFRIENDS_PFX_PASSWORD, $exe)
        }
        & signtool.exe @signArgs
        if ($LASTEXITCODE -eq 0) { $signed = $true }
    }
}

# Single source: app/paths.py APP_VERSION (this used to be a second hardcoded copy).
$verMatch = Select-String -Path "app\paths.py" -Pattern '^APP_VERSION\s*=\s*"([^"]+)"'
if (-not $verMatch) { throw "APP_VERSION not found in app/paths.py" }
$version = $verMatch.Matches[0].Groups[1].Value
$release = Join-Path (Get-Location) "output\release-$version"
if (Test-Path $release) { Remove-Item $release -Recurse -Force }
New-Item -ItemType Directory -Force -Path $release | Out-Null
# The ZIP extracts to one MorrowFriends\ folder: MorrowFriends.exe beside _internal\.
Copy-Item $appDir (Join-Path $release "MorrowFriends") -Recurse -Force
$zip = Join-Path $desktop "MorrowFriends-v$version-Windows.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
# Freshly copied files can be held open briefly (seen 2026-09-29 on
# _internal\base_library.zip right after the copy), so retry.
for ($i = 1; $i -le 5; $i++) {
    try {
        Compress-Archive -Path (Join-Path $release "MorrowFriends") -DestinationPath $zip -Force -ErrorAction Stop
        break
    } catch {
        if ($i -eq 5) { throw }
        Start-Sleep -Seconds 3
    }
}
$checksum = (Get-FileHash -Algorithm SHA256 -LiteralPath $zip).Hash
$checksumPath = "$zip.sha256"
Set-Content -LiteralPath $checksumPath -Value "$checksum  $(Split-Path $zip -Leaf)" -Encoding ascii

Write-Host "Built: $exe"
Write-Host "Bootloader: $bootHash"
Write-Host "Release: $release"
Write-Host "Zip: $zip"
Write-Host "Checksum: $checksumPath"
Write-Host "Signed: $signed"
Write-Host "Shortcut: $shortcutPath"
Write-Host ("Zip size: {0:N1} MB" -f ((Get-Item $zip).Length / 1MB))
