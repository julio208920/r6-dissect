# Builds the Windows app: dist\R6MatchStats (the app), dist\R6MatchStats-Setup.exe
# (the installer) and dist\R6MatchStats-Windows.zip (the portable version).
# Run from anywhere:  powershell -ExecutionPolicy Bypass -File desktop\build.ps1
# Needs Python 3.10+ (uses .venv if present), Go 1.23+ (or an existing r6-dissect.exe)
# and Inno Setup 6 for the installer (installed with winget or choco if missing).
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

if (Get-Command go -ErrorAction SilentlyContinue) {
    go build -o r6-dissect.exe .
    if ($LASTEXITCODE) { throw "go build failed" }
} elseif (-not (Test-Path r6-dissect.exe)) {
    throw "Install Go (https://go.dev/dl/) or build r6-dissect.exe first."
}

$python = if (Test-Path .venv\Scripts\python.exe) { ".venv\Scripts\python.exe" } else { "python" }
& $python -m pip install --quiet -r scripts\requirements.txt -r desktop\requirements-build.txt
if ($LASTEXITCODE) { throw "pip install failed" }

# the GitHub repo that the app's "check for a newer version" link points to
$repo = $env:GITHUB_REPOSITORY
if (-not $repo) { $repo = (git remote get-url origin) -replace '^.*github\.com[:/]', '' -replace '\.git$', '' }
New-Item -ItemType Directory -Force build | Out-Null
Set-Content -Path build\repo.txt -Value $repo -Encoding ascii
# the app's version: $env:R6_VERSION (the release workflow passes the tag), else the one in app_info.py
$version = $env:R6_VERSION -replace '^[vV]', ''
if (-not ($version -match '^\d+(\.\d+){0,3}$')) {
    $version = (Select-String -Path scripts\app_info.py -Pattern '"([\d.]+)"\s*$' | Where-Object { $_.Line -match 'APP_VERSION' }).Matches[0].Groups[1].Value
}
Set-Content -Path build\version.txt -Value $version -Encoding ascii

& $python -m PyInstaller --noconfirm --clean --distpath dist --workpath build\pyinstaller desktop\R6MatchStats.spec
if ($LASTEXITCODE) { throw "PyInstaller failed" }

# the portable zip. Python's zipfile, with retries: antivirus can briefly lock the files PyInstaller just wrote
foreach ($attempt in 1..3) {
    & $python -c "import shutil; shutil.make_archive('dist/R6MatchStats-Windows', 'zip', 'dist', 'R6MatchStats')"
    if (-not $LASTEXITCODE) { break }
    Start-Sleep -Seconds 5
}
if ($LASTEXITCODE) { throw "zipping dist\R6MatchStats failed" }

# the installer
function Find-Iscc {
    $found = Get-Command iscc -ErrorAction SilentlyContinue
    if ($found) { return $found.Source }
    foreach ($dir in "${env:ProgramFiles(x86)}\Inno Setup 6", "$env:ProgramFiles\Inno Setup 6", "$env:LOCALAPPDATA\Programs\Inno Setup 6") {
        if (Test-Path "$dir\ISCC.exe") { return "$dir\ISCC.exe" }
    }
}
$iscc = Find-Iscc
if (-not $iscc) {
    Write-Host "Installing Inno Setup 6..."
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install --id JRSoftware.InnoSetup --exact --silent --accept-package-agreements --accept-source-agreements | Out-Null
    } elseif (Get-Command choco -ErrorAction SilentlyContinue) {
        choco install innosetup -y --no-progress | Out-Null
    }
    $iscc = Find-Iscc
    if (-not $iscc) { throw "Install Inno Setup 6 (https://jrsoftware.org/isdl.php) to build the installer." }
}
& $iscc /Q "/DAppVersion=$version" "/DAppRepo=$repo" desktop\installer.iss
if ($LASTEXITCODE) { throw "Inno Setup failed" }

Write-Host "Built R6 Match Stats $version`:"
Write-Host "  dist\R6MatchStats-Setup.exe   (installer)"
Write-Host "  dist\R6MatchStats-Windows.zip (portable)"
