$ErrorActionPreference = "Stop"

$base = "D:\agent wallet\simulation_mvp"
Set-Location $base

$backendJob = Start-Job -ScriptBlock {
  Set-Location "D:\agent wallet\simulation_mvp"
  python backend\app.py
}

$callbackJob = Start-Job -ScriptBlock {
  Set-Location "D:\agent wallet\simulation_mvp"
  python agent\callback_server.py
}

Start-Sleep -Seconds 3

try {
  $expiresAt = (Get-Date).ToUniversalTime().AddMinutes(5).ToString("yyyy-MM-ddTHH:mm:ssK")
  $issuedAt = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssK")
  $reqId = "req_smoke_" + [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()

  $createBody = @{
    request_id   = $reqId
    agent_id     = "api_agent_001"
    payee        = "DeepSeek"
    amount       = 0.05
    purpose      = "buy 100 api calls"
    expires_at   = $expiresAt
    issued_at    = $issuedAt
    nonce        = "nonce_" + $reqId
    callback_url = "http://127.0.0.1:7001/callback"
  } | ConvertTo-Json

  $create = Invoke-RestMethod -Uri "http://127.0.0.1:5000/api/pay-requests" -Method Post `
    -Headers @{ "X-Agent-Token" = "dev-agent-token" } -ContentType "application/json" -Body $createBody

  $requestId = $create.request.request_id

  $pending = Invoke-RestMethod -Uri "http://127.0.0.1:5000/api/pending-requests" -Method Get `
    -Headers @{ "X-User-Token" = "dev-user-token" }

  $signBody = @{
    request_id = $requestId
    approval   = "user_approved"
    signed_by  = "smoke_script"
    signature  = "simulated_signature"
  } | ConvertTo-Json

  $sign = Invoke-RestMethod -Uri "http://127.0.0.1:5000/api/sign" -Method Post `
    -Headers @{ "X-User-Token" = "dev-user-token" } -ContentType "application/json" -Body $signBody

  $detail = Invoke-RestMethod -Uri ("http://127.0.0.1:5000/api/requests/" + $requestId) -Method Get `
    -Headers @{ "X-User-Token" = "dev-user-token" }

  Write-Host "Create message: $($create.message)"
  Write-Host "Pending count: $($pending.pending_requests.Count)"
  Write-Host "Sign message: $($sign.message)"
  Write-Host "Final status: $($detail.request.status)"

  if ($detail.request.status -ne "SUCCESS") {
    throw "Smoke test failed: final status is not SUCCESS"
  }

  Write-Host "Smoke test passed."
}
finally {
  Stop-Job $backendJob -ErrorAction SilentlyContinue | Out-Null
  Stop-Job $callbackJob -ErrorAction SilentlyContinue | Out-Null
  Receive-Job $backendJob -ErrorAction SilentlyContinue | Out-Null
  Receive-Job $callbackJob -ErrorAction SilentlyContinue | Out-Null
  Remove-Job $backendJob -ErrorAction SilentlyContinue
  Remove-Job $callbackJob -ErrorAction SilentlyContinue
}
