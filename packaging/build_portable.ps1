# Build the MorrowFriends release ZIP with NO PyInstaller exe.
#
# Ships python.org's signed embeddable Python + the launcher source, started by
# MorrowFriends.bat. Why: Microsoft Defender's cloud ML flags fresh unsigned
# PyInstaller exes per-hash (Trojan:Win32/Wacatac.*!ml). On 2026-09-30 two exes
# from the identical build config got opposite verdicts, and the v0.7.5
# PyInstaller release exe was quarantined on the build machine. Every PE file
# in this layout is either signed by its vendor or an unmodified PyPI wheel file.
param(
    [string]$Python = ".venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$root = (Get-Location).Path

$verMatch = Select-String -Path "app\paths.py" -Pattern '^APP_VERSION\s*=\s*"([^"]+)"'
if (-not $verMatch) { throw "APP_VERSION not found in app/paths.py" }
$version = $verMatch.Matches[0].Groups[1].Value

$pyVersion = (& $Python -c "import platform; print(platform.python_version())")
$basePrefix = (& $Python -c "import sys; print(sys.base_prefix)")
if ($LASTEXITCODE -ne 0) { throw "could not query $Python" }

$stageRoot = Join-Path $root "dist\portable"
$stage = Join-Path $stageRoot "MorrowFriends"
if (Test-Path $stageRoot) { Remove-Item $stageRoot -Recurse -Force }
$runtime = Join-Path $stage "runtime"
New-Item -ItemType Directory -Force -Path $runtime | Out-Null

# 1. Embeddable Python from python.org, same version as the build Python.
$cache = Join-Path $root "build\python-embed"
New-Item -ItemType Directory -Force -Path $cache | Out-Null
$embedZip = Join-Path $cache "python-$pyVersion-embed-amd64.zip"
if (-not (Test-Path $embedZip)) {
    Invoke-WebRequest -Uri "https://www.python.org/ftp/python/$pyVersion/python-$pyVersion-embed-amd64.zip" -OutFile $embedZip -UseBasicParsing
}
Expand-Archive -LiteralPath $embedZip -DestinationPath $runtime -Force
$sig = Get-AuthenticodeSignature (Join-Path $runtime "pythonw.exe")
if ($sig.Status -ne "Valid" -or $sig.SignerCertificate.Subject -notmatch "Python Software Foundation") {
    throw "pythonw.exe signature is not a valid Python Software Foundation signature: $($sig.Status) $($sig.SignerCertificate.Subject)"
}

# 2. tkinter is not in the embeddable package; take it from the matching full install.
foreach ($f in "DLLs\_tkinter.pyd", "DLLs\tcl86t.dll", "DLLs\tk86t.dll") {
    Copy-Item (Join-Path $basePrefix $f) $runtime -Force
}
New-Item -ItemType Directory -Force -Path (Join-Path $runtime "Lib") | Out-Null
Copy-Item (Join-Path $basePrefix "Lib\tkinter") (Join-Path $runtime "Lib\tkinter") -Recurse -Force
Copy-Item (Join-Path $basePrefix "tcl") (Join-Path $runtime "tcl") -Recurse -Force
Get-ChildItem $runtime -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force

# 3. Import path: stdlib zip, runtime, tkinter, bundled packages, app root.
$pyTag = "python" + (($pyVersion.Split(".")[0..1]) -join "")
[string[]]$pthLines = "$pyTag.zip", ".", "Lib", "..\site-packages", ".."
[IO.File]::WriteAllLines((Join-Path $runtime "$pyTag._pth"), $pthLines, (New-Object Text.ASCIIEncoding))
if ((Get-Content (Join-Path $runtime "$pyTag._pth")).Count -ne 5) { throw "$pyTag._pth was not written with 5 lines" }

# 4. Runtime dependencies at the exact versions the build venv has (no PyInstaller).
$sitePackages = Join-Path $stage "site-packages"
$constraints = Join-Path $cache "constraints.txt"
& $Python -m pip freeze | Where-Object { $_ -notmatch '^(-e |pyinstaller)' } | Set-Content $constraints -Encoding ascii
$reqs = Get-Content "requirements.txt" | Where-Object { $_ -and $_ -notmatch '^\s*#' -and $_ -notmatch '^pyinstaller' }
& $Python -m pip install --target $sitePackages -c $constraints --no-warn-script-location -q @reqs
if ($LASTEXITCODE -ne 0) { throw "pip install of runtime dependencies failed" }
# pip --target writes console-script launcher exes into bin\; nothing uses them.
$bin = Join-Path $sitePackages "bin"
if (Test-Path $bin) { Remove-Item $bin -Recurse -Force }
Get-ChildItem $sitePackages -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force

# 5. Launcher source + the assets it looks for under packaging\.
Copy-Item "run.py" $stage
New-Item -ItemType Directory -Force -Path (Join-Path $stage "app") | Out-Null
Copy-Item "app\*.py" (Join-Path $stage "app")
$pk = Join-Path $stage "packaging"
New-Item -ItemType Directory -Force -Path (Join-Path $pk "tes3mp_custom_scripts") | Out-Null
& $Python packaging/make_icon.py
if ($LASTEXITCODE -ne 0) { throw "icon generation failed" }
foreach ($f in "morrowfriends.png", "morrowfriends.ico", "MorrowFriends.voice.json") {
    Copy-Item (Join-Path "packaging" $f) $pk
}
Copy-Item "packaging\tes3mp_custom_scripts\*.lua" (Join-Path $pk "tes3mp_custom_scripts")
foreach ($doc in "LICENSE", "PRIVACY.md", "THIRD_PARTY_NOTICES.md", "packaging\START HERE - MorrowFriends.txt") {
    Copy-Item $doc $stage
}
# The guard matters: double-clicking the .bat inside WinRAR/7-Zip/Explorer's ZIP
# view unpacks only the .bat to a temp folder (seen 2026-09-30), and without it
# the user just gets "Windows cannot find ...\runtime\pythonw.exe".
$batLines = @(
    '@echo off',
    'rem MorrowFriends launcher. Runs the bundled Python; nothing is installed.',
    'if not exist "%~dp0runtime\pythonw.exe" goto notextracted',
    'start "" "%~dp0runtime\pythonw.exe" "%~dp0run.py" %*',
    'exit /b 0',
    ':notextracted',
    'title MorrowFriends',
    'echo.',
    'echo   MorrowFriends has to be extracted before it can run.',
    'echo.',
    'echo   You opened it from inside the ZIP, so the rest of its files are missing.',
    'echo   Close this window, right-click the ZIP, choose "Extract All",',
    'echo   then open the extracted MorrowFriends folder and run MorrowFriends.bat.',
    'echo.',
    'pause',
    'exit /b 1'
)
[IO.File]::WriteAllText((Join-Path $stage "MorrowFriends.bat"), (($batLines -join "`r`n") + "`r`n"), (New-Object Text.ASCIIEncoding))

# 6. Every exe that ships must carry a valid signature.
$unsigned = Get-ChildItem $stage -Recurse -Filter *.exe | Where-Object { (Get-AuthenticodeSignature $_.FullName).Status -ne "Valid" }
if ($unsigned) { throw "Unsigned exe in release: $($unsigned.FullName -join ', ')" }

# 7. ZIP + checksum on the Desktop.
$release = Join-Path $root "output\release-$version"
if (Test-Path $release) { Remove-Item $release -Recurse -Force }
New-Item -ItemType Directory -Force -Path $release | Out-Null
Copy-Item $stage (Join-Path $release "MorrowFriends") -Recurse -Force
$desktop = [Environment]::GetFolderPath("Desktop")
$zip = Join-Path $desktop "MorrowFriends-v$version-Windows.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
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
Set-Content -LiteralPath "$zip.sha256" -Value "$checksum  $(Split-Path $zip -Leaf)" -Encoding ascii

Write-Host "Stage: $stage"
Write-Host "Zip: $zip"
Write-Host "SHA-256: $checksum"
Write-Host ("Zip size: {0:N1} MB" -f ((Get-Item $zip).Length / 1MB))
