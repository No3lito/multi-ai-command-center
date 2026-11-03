# Turns on automatic updates for the Command Center on this computer.
#
# Creates a Windows scheduled task, "Multi-AI Command Center auto-update", that runs
# auto-update.ps1 hidden every few minutes while you are signed in. After you approve a code
# job (or anything is merged to main), the Command Center updates itself within that time.
#
#   Turn on:   powershell -ExecutionPolicy Bypass -File infrastructure\install-auto-update.ps1
#   Turn off:  powershell -ExecutionPolicy Bypass -File infrastructure\install-auto-update.ps1 -Remove
#   See what it did: logs\auto-update.log
param(
  [int]$Minutes = 5,
  [switch]$Remove
)
$ErrorActionPreference = "Stop"
$name = "Multi-AI Command Center auto-update"

if ($Remove) {
  if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false
    Write-Host "Automatic updates are OFF." -ForegroundColor Yellow
  } else {
    Write-Host "Automatic updates were not on."
  }
  exit 0
}

if ($Minutes -lt 2) { throw "Use at least 2 minutes." }
$vbs = Join-Path $PSScriptRoot "auto-update-hidden.vbs"
if (-not (Test-Path $vbs)) { throw "Missing $vbs" }

$action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$vbs`""
$every = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes $Minutes)
$atLogon = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
  -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $name -Action $action -Trigger @($every, $atLogon) -Settings $settings `
  -Principal $principal -Description "Pulls main from GitHub and rebuilds the Command Center when it changes." -Force | Out-Null
Start-ScheduledTask -TaskName $name

Write-Host "Automatic updates are ON: checked every $Minutes minutes while you are signed in." -ForegroundColor Green
Write-Host "What it does is written to logs\auto-update.log. To turn it off, run this script with -Remove."
