# Build friend-ready MorrowFriends.exe
param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

& $Python -m pip install -r requirements.txt -q
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
& $Python packaging/make_icon.py
if ($LASTEXITCODE -ne 0) { throw "icon generation failed" }
& $Python -m PyInstaller packaging/morrowfriends.spec --noconfirm
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$exe = Join-Path (Get-Location) "dist\MorrowFriends.exe"
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
    Copy-Item $voiceJson (Join-Path (Split-Path $exe -Parent) "MorrowFriends.voice.json") -Force
}
if (Test-Path $startHere) {
    Copy-Item $startHere (Join-Path (Split-Path $exe -Parent) "START HERE - MorrowFriends.txt") -Force
}
foreach ($doc in $releaseDocs) {
    if (Test-Path $doc) {
        Copy-Item $doc (Join-Path (Split-Path $exe -Parent) (Split-Path $doc -Leaf)) -Force
    }
}

$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop "MorrowFriends.lnk"
if (Test-Path $shortcutPath) { Remove-Item $shortcutPath -Force }
$wsh = New-Object -ComObject WScript.Shell
$sc = $wsh.CreateShortcut($shortcutPath)
$sc.TargetPath = $exe
$sc.WorkingDirectory = Split-Path $exe -Parent
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

$version = "0.7.4"
$release = Join-Path (Get-Location) "output\release-$version"
New-Item -ItemType Directory -Force -Path $release | Out-Null
Copy-Item $exe (Join-Path $release "MorrowFriends.exe") -Force
if (Test-Path $voiceJson) {
    Copy-Item $voiceJson (Join-Path $release "MorrowFriends.voice.json") -Force
}
if (Test-Path $startHere) {
    Copy-Item $startHere (Join-Path $release "START HERE - MorrowFriends.txt") -Force
}
foreach ($doc in $releaseDocs) {
    if (Test-Path $doc) {
        Copy-Item $doc (Join-Path $release (Split-Path $doc -Leaf)) -Force
    }
}
$zip = Join-Path ([Environment]::GetFolderPath("Desktop")) "MorrowFriends-v$version-Windows.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path (Join-Path $release "*") -DestinationPath $zip -Force
$checksum = (Get-FileHash -Algorithm SHA256 -LiteralPath $zip).Hash
$checksumPath = "$zip.sha256"
Set-Content -LiteralPath $checksumPath -Value "$checksum  $(Split-Path $zip -Leaf)" -Encoding ascii

Write-Host "Built: $exe"
Write-Host "Release: $release"
Write-Host "Zip: $zip"
Write-Host "Checksum: $checksumPath"
Write-Host "Signed: $signed"
Write-Host "Shortcut: $shortcutPath"
Write-Host ("Size: {0:N1} MB" -f ((Get-Item $exe).Length / 1MB))
