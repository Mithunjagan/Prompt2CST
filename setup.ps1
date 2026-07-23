param(
    [switch]$CreateDesktopShortcut
)

$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
$venvRoot = Join-Path $projectRoot ".venv"
$venvPython = Join-Path $venvRoot "Scripts\python.exe"

function Test-Python311 {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [string[]]$PrefixArguments = @()
    )

    try {
        $version = & $Executable @PrefixArguments -c `
            "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
        return ($LASTEXITCODE -eq 0 -and $version.Trim() -eq "3.11")
    }
    catch {
        return $false
    }
}

function Assert-NativeSuccess {
    param(
        [Parameter(Mandatory = $true)][string]$Step
    )

    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE."
    }
}

function Find-Python311 {
    $pyLauncher = Get-Command "py.exe" -ErrorAction SilentlyContinue
    if ($pyLauncher -and (Test-Python311 $pyLauncher.Source @("-3.11"))) {
        return @{
            Executable = $pyLauncher.Source
            Arguments = @("-3.11")
        }
    }

    $uv = Get-Command "uv.exe" -ErrorAction SilentlyContinue
    if ($uv) {
        try {
            $uvPython = (& $uv.Source python find 3.11 2>$null).Trim()
            if ($uvPython -and (Test-Python311 $uvPython)) {
                return @{
                    Executable = $uvPython
                    Arguments = @()
                }
            }
        }
        catch {
            # Continue through the remaining local candidates.
        }
    }

    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe")
    )
    $uvPythonRoot = Join-Path $env:APPDATA "uv\python"
    if (Test-Path $uvPythonRoot) {
        $candidates += Get-ChildItem $uvPythonRoot `
            -Filter "python.exe" `
            -Recurse `
            -File `
            -ErrorAction SilentlyContinue |
            Where-Object {
                $_.FullName -like "*cpython-3.11*-windows-x86_64-none*"
            } |
            Select-Object -ExpandProperty FullName
    }

    foreach ($candidate in $candidates) {
        if ((Test-Path $candidate) -and (Test-Python311 $candidate)) {
            return @{
                Executable = $candidate
                Arguments = @()
            }
        }
    }

    $pythonCommand = Get-Command "python.exe" -ErrorAction SilentlyContinue
    if ($pythonCommand -and (Test-Python311 $pythonCommand.Source)) {
        return @{
            Executable = $pythonCommand.Source
            Arguments = @()
        }
    }

    return $null
}

Write-Host ""
Write-Host "Prompt2CST setup" -ForegroundColor Cyan
Write-Host "Safe LLM-guided antenna design for CST Studio Suite 2026"
Write-Host ""

if (-not (Test-Path $venvPython)) {
    Write-Host "[1/5] Finding Python 3.11..."
    $python311 = Find-Python311
    if (-not $python311) {
        throw @"
Python 3.11 was not found.

Install Python 3.11 x64 from https://www.python.org/downloads/ or run:
    uv python install 3.11

Then run setup.bat again. Prompt2CST currently requires Python 3.11.
"@
    }

    Write-Host "[2/5] Creating the local virtual environment..."
    $basePython = $python311.Executable
    $baseArguments = $python311.Arguments
    & $basePython @baseArguments -m venv $venvRoot
    Assert-NativeSuccess "Virtual environment creation"
}
else {
    Write-Host "[1/5] Reusing .venv with Python 3.11."
    Write-Host "[2/5] Virtual environment is ready."
}

if (-not (Test-Python311 $venvPython)) {
    throw "The existing .venv is not Python 3.11. Delete only the .venv folder and run setup.bat again."
}

Write-Host "[3/5] Installing Prompt2CST and its dependencies..."
& $venvPython -m pip install --upgrade pip setuptools wheel
Assert-NativeSuccess "Python packaging-tool installation"
& $venvPython -m pip install -e $projectRoot
Assert-NativeSuccess "Prompt2CST dependency installation"

Write-Host "[4/5] Running offline safety and geometry tests..."
& $venvPython -m unittest discover -s (Join-Path $projectRoot "tests") -v
Assert-NativeSuccess "Prompt2CST test suite"

Write-Host "[5/5] Checking the CST 2026 registration..."
$cstRegistered = Test-Path `
    "Registry::HKEY_CLASSES_ROOT\CSTStudio.Application.2026"
if ($cstRegistered) {
    Write-Host "CSTStudio.Application.2026 is registered." -ForegroundColor Green
}
else {
    Write-Warning "CSTStudio.Application.2026 was not found. The UI can run, but CST builds will not work until CST 2026 is installed and registered."
}

New-Item -ItemType Directory -Force `
    (Join-Path $projectRoot "outputs") | Out-Null

if ($CreateDesktopShortcut) {
    $desktop = [Environment]::GetFolderPath("Desktop")
    $shortcutPath = Join-Path $desktop "Prompt2CST.lnk"
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = Join-Path $projectRoot "Prompt2CST.bat"
    $shortcut.WorkingDirectory = $projectRoot
    $shortcut.Description = "Prompt2CST RF Design Studio"
    $shortcut.Save()
    Write-Host "Desktop shortcut created: $shortcutPath"
}

Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
Write-Host "Double-click Prompt2CST.bat to launch."
Write-Host "Your OpenRouter API key is entered in the app and is not saved."
