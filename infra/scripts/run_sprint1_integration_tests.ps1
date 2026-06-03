$ErrorActionPreference = "Stop"

Set-Location "C:\xampp\htdocs\AIDublajStudio"

if (-not (Test-Path ".env")) {
  Copy-Item ".env.example" ".env"
}

docker compose --profile app up -d --build

Write-Host "Waiting for API..."
for ($i = 0; $i -lt 30; $i++) {
  try {
    $response = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/health" -Method Get
    if ($response.status -eq "ok") {
      break
    }
  } catch {
    Start-Sleep -Seconds 2
  }
}

$healthOk = $false
for ($i = 0; $i -lt 5; $i++) {
  try {
    $response = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/health" -Method Get
    if ($response.status -eq "ok") {
      $healthOk = $true
      break
    }
  } catch {
    Start-Sleep -Seconds 1
  }
}

if (-not $healthOk) {
  docker logs aidublaj-api-dev --tail 200
  throw "API failed health check."
}

docker compose exec api pytest tests/integration -q
