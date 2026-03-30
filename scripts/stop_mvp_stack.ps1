$ErrorActionPreference = "Stop"

$BaseDir = Split-Path -Parent $PSScriptRoot
$RuntimeDir = Join-Path $BaseDir ".runtime"
$PidFile = Join-Path $RuntimeDir "pids.json"

function Get-JsonFile([string]$Path) {
  if (-not (Test-Path $Path)) { return @{} }
  $raw = Get-Content -Raw $Path -ErrorAction SilentlyContinue
  if (-not $raw) { return @{} }
  try { return ($raw | ConvertFrom-Json -AsHashtable) } catch { return @{} }
}

function Stop-ProcessSafe([int]$Pid, [string]$Name) {
  if ($Pid -le 0) { return }
  try {
    $proc = Get-Process -Id $Pid -ErrorAction Stop
    Stop-Process -Id $proc.Id -Force -ErrorAction Stop
    Write-Host "[Aegis] Stopped $Name (PID=$Pid)"
  } catch {
    Write-Host "[Aegis] $Name not running (PID=$Pid)"
  }
}

$state = Get-JsonFile $PidFile
if ($state.Count -eq 0) {
  Write-Host "[Aegis] State file not found: $PidFile"
  exit 0
}

Stop-ProcessSafe -Pid ([int]$state.backend_pid) -Name "backend"
Stop-ProcessSafe -Pid ([int]$state.agent_pid) -Name "agent"
Stop-ProcessSafe -Pid ([int]$state.tunnel_pid) -Name "cloudflared"

Remove-Item -Path $PidFile -Force -ErrorAction SilentlyContinue
Write-Host "[Aegis] MVP stack stopped."
