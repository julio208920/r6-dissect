# Fail closed: no release assets are uploaded unless all configured scans finish.
# Sources: Microsoft Learn MpCmdRun reference; VirusTotal API v3 analyses reference.
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
Update-MpSignature -ErrorAction Stop
$mp = Get-MpComputerStatus
if (-not $mp.AntivirusEnabled -or -not $mp.AMServiceEnabled) { throw 'Microsoft Defender is unavailable.' }
if (-not $mp.AntivirusSignatureLastUpdated -or $mp.AntivirusSignatureLastUpdated -lt (Get-Date).AddDays(-2)) {
    throw 'Microsoft Defender signatures are missing or stale.'
}
$platform = Get-ChildItem "$env:ProgramData\Microsoft\Windows Defender\Platform" -Directory -ErrorAction SilentlyContinue |
    Sort-Object Name -Descending | Select-Object -First 1
$defender = if ($platform) { Join-Path $platform.FullName 'MpCmdRun.exe' } else { "$env:ProgramFiles\Windows Defender\MpCmdRun.exe" }
if (-not (Test-Path -LiteralPath $defender)) { throw 'Microsoft Defender scanner was not found.' }
$assets = 'dist\R6MatchStats-Setup.exe', 'dist\R6MatchStats-Windows.zip'
$hashes = @{}
foreach ($path in $assets) { $hashes[$path] = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLower() }
$report = @("R6 Match Stats $env:R6_VERSION - release verification", "Commit: $env:GITHUB_SHA", "UTC: $([DateTime]::UtcNow.ToString('o'))", '',
    "Microsoft Defender engine $($mp.AMEngineVersion), signatures $($mp.AntivirusSignatureVersion)")
foreach ($path in $assets + 'dist\R6MatchStats') {
    & $defender -Scan -ScanType 3 -File (Resolve-Path -LiteralPath $path).Path -DisableRemediation
    if ($LASTEXITCODE -ne 0) { throw "Defender reported a detection or scan failure for $path (exit $LASTEXITCODE)." }
    $report += "$(Split-Path $path -Leaf): no threats detected"
}
if ($env:VT_API_KEY) {
    $headers = @{ 'x-apikey' = $env:VT_API_KEY }
    foreach ($path in $assets) {
        $url = (Invoke-RestMethod 'https://www.virustotal.com/api/v3/files/upload_url' -Headers $headers).data
        $upload = Invoke-RestMethod -Method Post -Uri $url -Headers $headers -Form @{file = Get-Item -LiteralPath $path}
        $id = $upload.data.id
        if (-not $id) { throw 'VirusTotal did not return an analysis ID.' }
        $deadline = (Get-Date).AddMinutes(15)
        do {
            Start-Sleep -Seconds 20
            $analysis = (Invoke-RestMethod "https://www.virustotal.com/api/v3/analyses/$id" -Headers $headers).data.attributes
            if ((Get-Date) -gt $deadline) { throw 'VirusTotal analysis timed out. Release blocked.' }
        } until ($analysis.status -eq 'completed')
        if ($null -eq $analysis.stats.malicious -or $null -eq $analysis.stats.suspicious) { throw 'VirusTotal returned incomplete verdicts.' }
        if ($analysis.stats.malicious -gt 0 -or $analysis.stats.suspicious -gt 0) { throw "VirusTotal flagged $path. Release blocked for review." }
        if (($analysis.stats.harmless + $analysis.stats.undetected) -lt 1) { throw 'No VirusTotal engine returned a usable result.' }
        $report += "VirusTotal completed: https://www.virustotal.com/gui/file/$($hashes[$path])"
        $report += ($analysis.stats | ConvertTo-Json -Compress)
    }
} else {
    $report += 'VirusTotal: not configured; Microsoft Defender scan only.'
}
$checksums = @()
foreach ($path in $assets) {
    if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLower() -ne $hashes[$path]) { throw "Asset changed during scanning: $path" }
    $checksums += "$($hashes[$path])  $(Split-Path $path -Leaf)"
}
$checksums | Set-Content dist\SHA256SUMS.txt -Encoding ascii
$report += '', 'SHA-256 checksums:', $checksums, '', 'Checksums detect changed downloads when compared with a trusted copy. They are not a code signature or a guarantee that software is malware-free.'
$report | Set-Content dist\VirusScan.txt -Encoding utf8
Get-Content dist\VirusScan.txt
