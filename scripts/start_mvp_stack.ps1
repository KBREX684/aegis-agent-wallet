param(
  [switch]$NoAgent,
  [switch]$NoTunnel,
  [int]$AgentIntervalSeconds = 25
)

$ErrorActionPreference = "Stop"

$BaseDir = Split-Path -Parent $PSScriptRoot
$RuntimeDir = Join-Path $BaseDir ".runtime"
$PidFile = Join-Path $RuntimeDir "pids.json"
$BackendOut = Join-Path $RuntimeDir "backend.out.log"
$BackendErr = Join-Path $RuntimeDir "backend.err.log"
$AgentOut = Join-Path $RuntimeDir "agent.out.log"
$AgentErr = Join-Path $RuntimeDir "agent.err.log"
$TunnelOut = Join-Path $RuntimeDir "cloudflared.out.log"
$TunnelErr = Join-Path $RuntimeDir "cloudflared.err.log"

function Ensure-Dir([string]$Path) {
  if (-not (Test-Path $Path)) {
    New-Item -Path $Path -ItemType Directory | Out-Null
  }
}

function Get-JsonFile([string]$Path) {
  if (-not (Test-Path $Path)) { return @{} }
  $raw = Get-Content -Raw $Path -ErrorAction SilentlyContinue
  if (-not $raw) { return @{} }
  try { return ($raw | ConvertFrom-Json -AsHashtable) } catch { return @{} }
}

function Save-JsonFile([string]$Path, $Obj) {
  $Obj | ConvertTo-Json -Depth 10 | Set-Content -Path $Path -Encoding UTF8
}

function Stop-ProcessSafe([int]$Pid) {
  if ($Pid -le 0) { return }
  try {
    $proc = Get-Process -Id $Pid -ErrorAction Stop
    Stop-Process -Id $proc.Id -Force -ErrorAction Stop
  } catch {
  }
}

function Stop-OldStack {
  $old = Get-JsonFile $PidFile
  foreach ($k in @("backend_pid", "agent_pid", "tunnel_pid")) {
    if ($old.ContainsKey($k)) {
      Stop-ProcessSafe -Pid ([int]$old[$k])
    }
  }
}

function Wait-Health([string]$Url, [int]$TimeoutSec = 25) {
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  while ((Get-Date) -lt $deadline) {
    try {
      $resp = Invoke-RestMethod -Uri $Url -Method Get -TimeoutSec 3
      if ($resp.status -eq "ok") { return $true }
    } catch {}
    Start-Sleep -Milliseconds 700
  }
  return $false
}

function Wait-TunnelUrl([string]$ErrLog, [string]$OutLog, [int]$TimeoutSec = 40) {
  $pattern = "https://[-a-z0-9]+\.trycloudflare\.com"
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  while ((Get-Date) -lt $deadline) {
    $combined = ""
    if (Test-Path $ErrLog) { $combined += (Get-Content -Raw $ErrLog -ErrorAction SilentlyContinue) + "`n" }
    if (Test-Path $OutLog) { $combined += (Get-Content -Raw $OutLog -ErrorAction SilentlyContinue) + "`n" }
    $m = [regex]::Match($combined, $pattern)
    if ($m.Success) { return $m.Value }
    Start-Sleep -Milliseconds 800
  }
  return ""
}

Ensure-Dir $RuntimeDir
Stop-OldStack

"" | Set-Content -Path $BackendOut -Encoding UTF8
"" | Set-Content -Path $BackendErr -Encoding UTF8
"" | Set-Content -Path $AgentOut -Encoding UTF8
"" | Set-Content -Path $AgentErr -Encoding UTF8
"" | Set-Content -Path $TunnelOut -Encoding UTF8
"" | Set-Content -Path $TunnelErr -Encoding UTF8

Write-Host "[Aegis] Starting backend..."
$backendProc = Start-Process -FilePath "python" -ArgumentList "backend\app.py" -WorkingDirectory $BaseDir -RedirectStandardOutput $BackendOut -RedirectStandardError $BackendErr -PassThru

if (-not (Wait-Health -Url "http://127.0.0.1:5000/health" -TimeoutSec 30)) {
  Write-Host "[Aegis] Backend failed to start. Check log: $BackendErr" -ForegroundColor Red
  Stop-ProcessSafe -Pid $backendProc.Id
  exit 1
}

$agentPid = 0
if (-not $NoAgent) {
  Write-Host "[Aegis] Starting simulated agent..."
  $agentArgs = @(
    "agent\agent_sim.py",
    "--mode", "interval",
    "--interval", "$AgentIntervalSeconds",
    "--server", "http://127.0.0.1:5000",
    "--agent-token", "dev-agent-token",
    "--agent-id", "api_agent_001",
    "--payee", "DeepSeek",
    "--amount", "0.05",
    "--purpose", "buy_api_calls"
  )
  $agentProc = Start-Process -FilePath "python" -ArgumentList $agentArgs -WorkingDirectory $BaseDir -RedirectStandardOutput $AgentOut -RedirectStandardError $AgentErr -PassThru
  $agentPid = $agentProc.Id
}

$tunnelPid = 0
$publicUrl = ""
if (-not $NoTunnel) {
  $cloudflaredExe = Join-Path $BaseDir "tools\cloudflared.exe"
  if (-not (Test-Path $cloudflaredExe)) {
    Write-Host "[Aegis] cloudflared.exe not found: $cloudflaredExe" -ForegroundColor Red
    Stop-ProcessSafe -Pid $backendProc.Id
    if ($agentPid -gt 0) { Stop-ProcessSafe -Pid $agentPid }
    exit 1
  }
  Write-Host "[Aegis] Starting temporary public tunnel..."
  $tunnelProc = Start-Process -FilePath $cloudflaredExe -ArgumentList @("tunnel", "--url", "http://127.0.0.1:5000", "--no-autoupdate") -WorkingDirectory $BaseDir -RedirectStandardOutput $TunnelOut -RedirectStandardError $TunnelErr -PassThru
  $tunnelPid = $tunnelProc.Id
  $publicUrl = Wait-TunnelUrl -ErrLog $TunnelErr -OutLog $TunnelOut -TimeoutSec 50
}

$state = @{
  started_at = (Get-Date).ToString("s")
  base_dir = $BaseDir
  backend_pid = $backendProc.Id
  agent_pid = $agentPid
  tunnel_pid = $tunnelPid
  local_url = "http://127.0.0.1:5000"
  public_url = $publicUrl
  logs = @{
    backend_out = $BackendOut
    backend_err = $BackendErr
    agent_out = $AgentOut
    agent_err = $AgentErr
    tunnel_out = $TunnelOut
    tunnel_err = $TunnelErr
  }
}
Save-JsonFile -Path $PidFile -Obj $state

Write-Host ""
Write-Host "================= Aegis MVP Started =================" -ForegroundColor Green
Write-Host "Local URL: http://127.0.0.1:5000"
if ($publicUrl) {
  Write-Host "Public URL: $publicUrl" -ForegroundColor Cyan
} elseif (-not $NoTunnel) {
  Write-Host "Public URL: not resolved in time, check $TunnelErr" -ForegroundColor Yellow
}
if ($agentPid -gt 0) {
  Write-Host "Agent PID: $agentPid"
} else {
  Write-Host "Agent: not started (NoAgent)"
}
Write-Host "Backend PID: $($backendProc.Id)"
if ($tunnelPid -gt 0) { Write-Host "Tunnel PID: $tunnelPid" }
Write-Host "State file: $PidFile"
Write-Host "Stop command: powershell -ExecutionPolicy Bypass -File `"$PSScriptRoot\stop_mvp_stack.ps1`""
Write-Host "===================================================="
