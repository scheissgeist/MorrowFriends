# Real-Defender gate for release exes.
# Copies each file to a temp folder, marks it as downloaded from the internet
# (Zone.Identifier ZoneId=3, the mark a browser download carries), then tries to
# read it. Defender's cloud check only fires for marked files: on 2026-09-30 a
# plain MpCmdRun scan passed an exe that this gate showed Defender blocking.
# Exit code = number of blocked files.
param(
    [Parameter(Mandatory = $true)][string[]]$Path,
    [int]$WaitSeconds = 20
)

$ErrorActionPreference = "Stop"
$work = Join-Path $env:TEMP ("mf-defender-gate-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory -Force -Path $work | Out-Null
$blocked = 0
$i = 0
foreach ($src in $Path) {
    $i++
    $name = "{0:D2}-{1}" -f $i, (Split-Path $src -Leaf)
    $dst = Join-Path $work $name
    $verdict = "PASS"
    $threat = ""
    $hash = "------------"
    try {
        $hash = (Get-FileHash -LiteralPath $src).Hash.Substring(0, 12)
        Copy-Item -LiteralPath $src -Destination $dst -Force
        Set-Content -LiteralPath $dst -Stream Zone.Identifier -Value "[ZoneTransfer]`r`nZoneId=3`r`nHostUrl=https://www.nexusmods.com/morrowind/mods/60201"
        Start-Sleep -Seconds 2
        $null = Get-FileHash -LiteralPath $dst
        Start-Sleep -Seconds $WaitSeconds
        if (-not (Test-Path -LiteralPath $dst)) { $verdict = "BLOCKED (removed)" }
        else { $null = Get-FileHash -LiteralPath $dst }
    } catch {
        $verdict = "BLOCKED"
    }
    if ($verdict -ne "PASS") {
        $blocked++
        $det = Get-MpThreatDetection -ErrorAction SilentlyContinue |
            Where-Object { $r = $_.Resources -join ";"; $r -like "*$name*" -or $r -like "*$src*" } |
            Sort-Object InitialDetectionTime -Descending | Select-Object -First 1
        if ($det) { $threat = (Get-MpThreat -ThreatID $det.ThreatID -ErrorAction SilentlyContinue).ThreatName }
    }
    "{0,-22} {1}  {2}  {3}" -f $verdict, $hash, $threat, $src
}
exit $blocked
