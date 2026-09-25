param(
    [Parameter(Mandatory=$true)][string]$File,
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-fA-F0-9]{64}$')][string]$ExpectedSHA256
)
$ErrorActionPreference = 'Stop'
$actual = (Get-FileHash -LiteralPath $File -Algorithm SHA256).Hash
if ($actual -ne $ExpectedSHA256) { throw 'Checksum mismatch. This file differs from the published release. Do not install it.' }
Write-Output 'Checksum matches the expected release file.'
