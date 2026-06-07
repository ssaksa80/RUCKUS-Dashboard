# RUCKUS DSO Dashboard - launcher (Windows PowerShell).
# Loads RUCKUS\.env, runs the dashboard in the foreground.
$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

if (-not (Test-Path "RUCKUS\.env") -or -not (Test-Path ".venv")) {
    Write-Error "Not installed. Run .\scripts\install.ps1 first."
    exit 1
}

Get-Content "RUCKUS\.env" | ForEach-Object {
    if ($_ -match '^([^#=]+)=(.*)$') {
        [Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), "Process")
    }
}
& .venv\Scripts\python.exe -m ruckus_dashboard --no-browser
