param(
    [string]$UnityEditorPath = $env:UNITY_EDITOR_PATH
)

$ErrorActionPreference = "Stop"
$projectPath = Join-Path $PSScriptRoot "R6MatchStats"

if (-not $UnityEditorPath) {
    $UnityEditorPath = "C:\Program Files\Unity\Hub\Editor\6000.0.34f1\Editor\Unity.exe"
}
if (-not (Test-Path $UnityEditorPath)) {
    throw "Unity Editor was not found. Install Unity 6000.0.34f1 or set UNITY_EDITOR_PATH."
}

$logPath = Join-Path $projectPath "Builds\unity-build.log"
& $UnityEditorPath -batchmode -quit -nographics -projectPath $projectPath `
    -executeMethod R6MatchIntelligence.Editor.BuildEntry.BuildWindows -logFile $logPath
if ($LASTEXITCODE) {
    Get-Content $logPath -ErrorAction SilentlyContinue
    throw "Unity Windows build failed with exit code $LASTEXITCODE."
}

Write-Host "Built $projectPath\Builds\Windows\R6MatchStats.exe"