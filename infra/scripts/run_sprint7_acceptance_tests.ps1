$ErrorActionPreference = "Stop"

Set-Location "C:\xampp\htdocs\AIDublajStudio"

$env:ASR_PROVIDER = "mock"
$env:TRANSLATION_PROVIDER = "mock"
$env:DIARIZATION_PROVIDER = "mock"

function Test-DockerAvailable {
  try {
    docker version | Out-Null
    return $true
  } catch {
    return $false
  }
}

function Write-DockerPsReport {
  try {
    Write-Host "Docker container status:"
    $dockerPsOutput = docker ps -a --format "table {{.Names}}`t{{.Status}}`t{{.Ports}}" | Out-String
    Write-Host $dockerPsOutput.TrimEnd()
    return $true
  } catch {
    Write-Warning "Docker ps unavailable: $($_.Exception.Message)"
    return $false
  }
}

function Assert-LastExitCode {
  param(
    [string]$CommandName
  )

  if ($LASTEXITCODE -ne 0) {
    throw "$CommandName failed with exit code $LASTEXITCODE."
  }
}

function Wait-ForWorkerMediaFfmpeg {
  param(
    [int]$Attempts = 60,
    [int]$DelaySeconds = 2
  )

  for ($i = 0; $i -lt $Attempts; $i++) {
    docker compose exec -T worker-media sh -c "command -v ffmpeg >/dev/null 2>&1"
    if ($LASTEXITCODE -eq 0) {
      return
    }
    Start-Sleep -Seconds $DelaySeconds
  }

  throw "worker-media ffmpeg did not become ready in time."
}

$testsPassed = $false
$cleanupStatus = "Cleanup skipped."

try {
  if (-not (Test-DockerAvailable)) {
    throw "Docker daemon is not available."
  }

  $projectsPath = "C:\xampp\htdocs\AIDublajStudio\storage\projects"
  Get-ChildItem $projectsPath -Force | Where-Object { $_.Name -ne ".gitkeep" } | Remove-Item -Recurse -Force

  docker compose --profile app down -v --remove-orphans
  Assert-LastExitCode "docker compose down"
  docker compose --profile app up -d --build
  Assert-LastExitCode "docker compose up"

  Write-Host "Waiting for API..."
  $apiReady = $false
  for ($i = 0; $i -lt 60; $i++) {
    try {
      $response = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/health" -Method Get
      if ($response.status -eq "ok") {
        $apiReady = $true
        break
      }
    } catch {
      Start-Sleep -Seconds 2
    }
  }
  if (-not $apiReady) {
    throw "API did not become healthy in time."
  }

  $sampleVideoHostPath = "C:\xampp\htdocs\AIDublajStudio\storage\tmp\sprint2-sample.mp4"
  if (-not (Test-Path $sampleVideoHostPath)) {
    Wait-ForWorkerMediaFfmpeg
    docker compose exec -T worker-media sh -c "mkdir -p /workspace/storage/tmp && ffmpeg -y -f lavfi -i color=c=black:s=320x240:d=4 -f lavfi -i sine=frequency=880:duration=4 -shortest -c:v libx264 -pix_fmt yuv420p -c:a aac /workspace/storage/tmp/sprint2-sample.mp4 >/tmp/ffmpeg-sample.log 2>&1"
    Assert-LastExitCode "worker-media sample video generation"
  }

  docker compose exec api pytest tests/integration/test_sprint7_acceptance.py -q -rA
  Assert-LastExitCode "Sprint 7 acceptance tests"
  $testsPassed = $true
  Write-Host "Sprint 7 acceptance tests passed."
} finally {
  if (Test-DockerAvailable) {
    try {
      $null = Write-DockerPsReport
      docker compose --profile app down -v --remove-orphans
      if ($LASTEXITCODE -eq 0) {
        $cleanupStatus = "Cleanup completed."
      } else {
        $cleanupStatus = "Cleanup failed: docker compose down exited with code $LASTEXITCODE."
      }
    } catch {
      $cleanupStatus = "Cleanup failed: $($_.Exception.Message)"
    }
  } else {
    $cleanupStatus = "Cleanup skipped: Docker daemon unavailable."
  }

  Write-Host $cleanupStatus
}

if (-not $testsPassed) {
  throw "Sprint 7 acceptance tests failed."
}
