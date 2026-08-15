<#
Amazon Warehouse Job Alert - setup script

What this does:
  1. Checks that Python is installed.
  2. Creates a local virtual environment (.venv) in this folder.
  3. Installs the required Python packages (Playwright, Twilio).
  4. Downloads the Chromium browser Playwright needs.
  5. Registers a Windows Scheduled Task that runs the checker every 10
     minutes, silently, in the background.

Run this from PowerShell in this folder:
    powershell -ExecutionPolicy Bypass -File setup.ps1
#>

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

Write-Host "== Amazon Warehouse Job Alert - Setup ==" -ForegroundColor Cyan

# 1. Find a working Python. Prefer the 'py' launcher (installed by the
#    official python.org installer) since the plain 'python' command on
#    some machines resolves to the Windows Store alias stub instead of a
#    real interpreter.
$UsePyLauncher = $false

$pyLauncher = Get-Command py -ErrorAction SilentlyContinue
if ($pyLauncher) {
    $verOut = & py -3 --version 2>&1 | Out-String
    if ($LASTEXITCODE -eq 0 -and $verOut -match "Python \d") {
        $UsePyLauncher = $true
        Write-Host "Found Python via 'py' launcher: $($verOut.Trim())"
    }
}

if (-not $UsePyLauncher) {
    $verOut = & python --version 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0 -or $verOut -notmatch "Python \d") {
        Write-Host "Couldn't find a working Python install." -ForegroundColor Red
        Write-Host ""
        Write-Host "Fix:"
        Write-Host "  1. Install Python 3.10+ from https://www.python.org/downloads/"
        Write-Host "     (tick 'Add python.exe to PATH' during install)."
        Write-Host "  2. Close this window, open a NEW PowerShell window, and re-run setup.ps1."
        exit 1
    }
    Write-Host "Found Python: $($verOut.Trim())"
}

function Invoke-BasePython {
    if ($UsePyLauncher) {
        & py -3 @args
    } else {
        & python @args
    }
}

# 2. Create virtual environment
if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment (.venv)..."
    Invoke-BasePython -m venv .venv
} else {
    Write-Host "Virtual environment already exists, reusing it."
}

$venvPython  = Join-Path $ScriptDir ".venv\Scripts\python.exe"
$venvPythonw = Join-Path $ScriptDir ".venv\Scripts\pythonw.exe"

if (-not (Test-Path $venvPython)) {
    Write-Host "ERROR: Virtual environment creation failed - $venvPython was never created." -ForegroundColor Red
    Write-Host "Try deleting the '.venv' folder in this directory and re-running setup.ps1."
    Write-Host "If it keeps failing, run 'python -m venv .venv' manually in this folder and read the error it prints."
    exit 1
}

# 3. Install requirements
Write-Host "Installing Python packages (this can take a minute)..."
& $venvPython -m pip install --upgrade pip | Out-Null
& $venvPython -m pip install -r requirements.txt

# 4. Install Playwright's Chromium browser
Write-Host "Downloading the Chromium browser for Playwright (one-time, ~150MB)..."
& $venvPython -m playwright install chromium

# 5. Check config.json has been filled in
$config = Get-Content "config.json" -Raw | ConvertFrom-Json
if ($config.twilio_account_sid -like "PASTE_YOUR*") {
    Write-Host ""
    Write-Host "NOTE: config.json still has placeholder Twilio values." -ForegroundColor Yellow
    Write-Host "Phone call and text alerts will be skipped until you fill those in."
    Write-Host "Sound + popup alerts will still work."
}

# 6. Register the Scheduled Task
$taskName = "AmazonWarehouseJobAlert"
$scriptPath = Join-Path $ScriptDir "check_jobs.py"

Write-Host "Registering Windows Scheduled Task '$taskName' (runs every 10 minutes)..."

$action = New-ScheduledTaskAction -Execute $venvPythonw -Argument "`"$scriptPath`"" -WorkingDirectory $ScriptDir
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 10) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null

Write-Host ""
Write-Host "Done! The task '$taskName' is now scheduled to check every 10 minutes." -ForegroundColor Green
Write-Host ""
Write-Host "Before you trust it, test it manually:"
Write-Host "  .\.venv\Scripts\python.exe test_alerts.py     (tests popup/sound + Twilio call/text)"
Write-Host "  .\.venv\Scripts\python.exe check_jobs.py      (runs one real check now)"
Write-Host ""
Write-Host "To stop it later, run uninstall.ps1."
