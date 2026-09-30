<#
Signs Windows programs with the app's code-signing certificate. desktop\build.ps1 signs the
app's own programs with it (before their SHA-256s go into the app's file list), and Inno Setup
signs the installer and uninstaller with it (installer.iss).

The certificate is the .pfx file at $env:R6_SIGN_PFX, with its password in
$env:R6_SIGN_PFX_PASSWORD. Every signature is timestamped, so it stays valid after the
certificate expires. $env:R6_SIGN_URL, if set, is the "more info" link shown with it.

    powershell -ExecutionPolicy Bypass -File desktop\sign.ps1 FILE [FILE ...]
#>
param([Parameter(Mandatory = $true, ValueFromRemainingArguments = $true)][string[]] $Files)
$ErrorActionPreference = "Stop"

if (-not $env:R6_SIGN_PFX -or -not (Test-Path $env:R6_SIGN_PFX)) {
    throw "No signing certificate: set R6_SIGN_PFX to a .pfx file, and R6_SIGN_PFX_PASSWORD to its password."
}

function Find-SignTool {
    $found = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($found) { return $found.Source }
    # the Windows SDK's, newest first (bin\10.0.26100.0\x64\signtool.exe sorts after bin\10.0.22621.0\...)
    $kits = Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin"
    $tool = Get-ChildItem $kits -Filter signtool.exe -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.Directory.Name -eq "x64" } | Sort-Object FullName -Descending | Select-Object -First 1
    if (-not $tool) { throw "signtool.exe wasn't found: install the Windows SDK's Signing Tools." }
    return $tool.FullName
}

$signtool = Find-SignTool
# RFC 3161 timestamp servers, tried in turn: any one of them being down mustn't fail a release
$timestampServers = "http://timestamp.digicert.com", "http://timestamp.sectigo.com", "http://time.certum.pl"
$common = @("sign", "/fd", "SHA256", "/td", "SHA256", "/f", $env:R6_SIGN_PFX, "/d", "R6 Match Stats")
if ($env:R6_SIGN_PFX_PASSWORD) { $common += "/p", $env:R6_SIGN_PFX_PASSWORD }
if ($env:R6_SIGN_URL) { $common += "/du", $env:R6_SIGN_URL }

foreach ($file in $Files) {
    if (-not (Test-Path $file)) { throw "Nothing to sign at $file" }
    $signed = $false
    foreach ($attempt in 1..2) {
        foreach ($server in $timestampServers) {
            & $signtool @common /tr $server $file
            if ($LASTEXITCODE -eq 0) { $signed = $true; break }
            Start-Sleep -Seconds 3
        }
        if ($signed) { break }
    }
    if (-not $signed) { throw "Couldn't sign $file" }
    Write-Host "Signed $file"
}
