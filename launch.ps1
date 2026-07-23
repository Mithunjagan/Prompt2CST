$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    throw "Prompt2CST is not set up yet. Double-click setup.bat first."
}

Set-Location $projectRoot
& $python -m prompt2cst.gui
if ($LASTEXITCODE -ne 0) {
    throw "Prompt2CST exited with code $LASTEXITCODE."
}
