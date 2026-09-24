$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    throw "Prompt2CST is not set up yet. Double-click setup.bat first."
}

# Refresh optional user-level Ollama settings even when Explorer was opened
# before those environment variables were added. The model remains opt-in.
foreach ($variableName in @("PROMPT2CST_OLLAMA_EXE", "OLLAMA_MODELS")) {
    if (-not [Environment]::GetEnvironmentVariable($variableName, "Process")) {
        $userValue = [Environment]::GetEnvironmentVariable($variableName, "User")
        if ($userValue) {
            [Environment]::SetEnvironmentVariable($variableName, $userValue, "Process")
        }
    }
}

Set-Location $projectRoot
& $python -m prompt2cst.gui
if ($LASTEXITCODE -ne 0) {
    throw "Prompt2CST exited with code $LASTEXITCODE."
}
