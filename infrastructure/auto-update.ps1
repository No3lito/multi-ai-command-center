# Keeps the Command Center on this computer up to date with GitHub's main branch.
#
# Run by the scheduled task that infrastructure\install-auto-update.ps1 sets up (every few
# minutes, hidden). When main on GitHub has new commits, for example after the owner approved
# a code job, it pulls them and rebuilds the containers, then checks that the app is healthy.
#
# Safe by design:
#  - Only acts when this folder is on the main branch with no uncommitted changes to tracked
#    files (.env and the generated compose override are untracked and never touched).
#  - Only fast-forwards (never merges, rebases or discards anything).
#  - One run at a time; does nothing when Docker is not running.
# Everything it does is written to logs\auto-update.log.
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $repo "logs"
$log = Join-Path $logDir "auto-update.log"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Write-Log([string]$text) {
  $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $text"
  Add-Content -Path $log -Value $line
  Write-Host $line
}

function Find-Tool([string]$name, [string[]]$fallbacks) {
  $cmd = Get-Command $name -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  foreach ($f in $fallbacks) { if (Test-Path $f) { return $f } }
  return $null
}

$mutex = New-Object System.Threading.Mutex($false, "Global\MultiAICommandCenterAutoUpdate")
if (-not $mutex.WaitOne(0)) { exit 0 }  # another run is still going
try {
  Set-Location $repo
  $git = Find-Tool "git" @("C:\Program Files\Git\cmd\git.exe")
  $docker = Find-Tool "docker" @("C:\Program Files\Docker\Docker\resources\bin\docker.exe")
  if (-not $git -or -not $docker) { Write-Log "SKIP: git or docker not found."; exit 0 }

  $branch = (& $git rev-parse --abbrev-ref HEAD).Trim()
  if ($branch -ne "main") { exit 0 }  # the owner is testing another branch: leave it alone
  $dirty = & $git status --porcelain --untracked-files=no
  if ($dirty) { Write-Log "SKIP: tracked files have local changes; not updating."; exit 0 }

  & $git fetch --quiet origin main
  if ($LASTEXITCODE -ne 0) { Write-Log "SKIP: could not reach GitHub."; exit 0 }
  $local = (& $git rev-parse HEAD).Trim()
  $remote = (& $git rev-parse origin/main).Trim()
  if ($local -eq $remote) { exit 0 }  # already up to date (the usual case: no log line)
  & $git merge-base --is-ancestor $local $remote
  if ($LASTEXITCODE -ne 0) { Write-Log "SKIP: this copy has commits GitHub does not; not updating."; exit 0 }

  & $docker info --format "{{.ServerVersion}}" *> $null
  if ($LASTEXITCODE -ne 0) { Write-Log "SKIP: Docker is not running; will try again next time."; exit 0 }

  $changes = (& $git log --format="%h %s" "$local..$remote") -join "; "
  Write-Log "UPDATE: $($local.Substring(0,7)) -> $($remote.Substring(0,7)): $changes"
  & $git merge --ff-only --quiet origin/main
  if ($LASTEXITCODE -ne 0) { Write-Log "FAILED: git could not fast-forward."; exit 1 }

  $build = & $docker compose up -d --build 2>&1 | Out-String
  if ($LASTEXITCODE -ne 0) {
    Write-Log "FAILED: docker compose up -d --build. Last lines:"
    Add-Content -Path $log -Value (($build -split "`n") | Select-Object -Last 25)
    exit 1
  }

  $healthy = $false
  for ($i = 0; $i -lt 30 -and -not $healthy; $i++) {
    Start-Sleep -Seconds 3
    try {
      $r = Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/health" -UseBasicParsing -TimeoutSec 3
      $healthy = $r.StatusCode -eq 200
    } catch { }
  }
  if ($healthy) { Write-Log "OK: updated to $($remote.Substring(0,7)) and the app is healthy." }
  else {
    Write-Log "WARNING: updated to $($remote.Substring(0,7)) but the app did not answer within 90 seconds. Last app log lines:"
    Add-Content -Path $log -Value (& $docker compose logs app --tail 25 2>&1 | Out-String)
  }

  # Keep the log short.
  $lines = Get-Content $log
  if ($lines.Count -gt 1000) { $lines | Select-Object -Last 500 | Set-Content $log }
}
finally {
  $mutex.ReleaseMutex()
}
