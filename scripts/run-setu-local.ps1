# Runs the latest Setu build (branch feat/core-completion) on this computer.
# It clones into E:\setu-local so your working copy in "E:\NGO Compliance system" is not touched.
# Usage: right-click this file > Run with PowerShell
#   or:  powershell -ExecutionPolicy Bypass -File ".\run-setu-local.ps1"
$ErrorActionPreference = "Stop"
$target = "E:\setu-local"
$repo = "https://github.com/nagarajnattonai-commits/NGO_compilance_system.git"
$branch = "feat/core-completion"

foreach ($tool in "git", "python", "npm.cmd") {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw "$tool is not installed or not on PATH" }
}

if (-not (Test-Path "$target\.git")) {
    Write-Host "Cloning $branch into $target ..."
    git clone --branch $branch $repo $target
} else {
    Write-Host "Updating $target ..."
    git -C $target fetch origin $branch
    git -C $target checkout $branch
    git -C $target pull --ff-only origin $branch
}

Write-Host "Installing API dependencies ..."
Set-Location "$target\apps\api"
if (-not (Test-Path ".venv")) { python -m venv .venv }
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

Write-Host "Installing web dependencies ..."
Set-Location "$target\apps\web"
npm.cmd install

# Development mode: SQLite database in apps\api, demo organizations seeded, no real email or WhatsApp.
# Emails (sign-up verification, password reset) are saved as files in the outbox folder instead of being sent.
$outbox = "$target\dev-outbox"
New-Item -ItemType Directory -Force -Path $outbox | Out-Null
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$target\apps\api'; `$env:APP_ENV='development'; `$env:DEV_EMAIL_OUTBOX_DIR='$outbox'; .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$target\apps\web'; npm.cmd run dev"

Write-Host "Waiting for the web app to start ..."
for ($i = 0; $i -lt 60; $i++) {
    try { Invoke-WebRequest "http://localhost:3000" -UseBasicParsing -TimeoutSec 3 | Out-Null; break } catch { Start-Sleep -Seconds 3 }
}
Start-Process "http://localhost:3000/signup"
Write-Host "Setu is running. Web: http://localhost:3000  API docs: http://127.0.0.1:8000/docs"
Write-Host "Verification and password-reset emails are saved in $outbox - open the newest file and click its link."
Start-Process explorer.exe $outbox
Write-Host "Close the two new PowerShell windows to stop it."
