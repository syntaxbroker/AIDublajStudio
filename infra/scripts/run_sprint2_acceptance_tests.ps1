$ErrorActionPreference = "Stop"

Set-Location "C:\xampp\htdocs\AIDublajStudio"

$projectsPath = "C:\xampp\htdocs\AIDublajStudio\storage\projects"
Get-ChildItem $projectsPath -Force | Where-Object { $_.Name -ne ".gitkeep" } | Remove-Item -Recurse -Force

docker compose --profile app down -v --remove-orphans
docker compose --profile app up -d --build

Write-Host "Waiting for API and worker..."
for ($i = 0; $i -lt 60; $i++) {
  try {
    $response = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/health" -Method Get
    if ($response.status -eq "ok") {
      break
    }
  } catch {
    Start-Sleep -Seconds 2
  }
}

docker exec aidublaj-worker-media-dev sh -c "mkdir -p /workspace/storage/tmp && ffmpeg -y -f lavfi -i color=c=black:s=320x240:d=1 -f lavfi -i anullsrc=r=44100:cl=mono -shortest -c:v libx264 -pix_fmt yuv420p -c:a aac /workspace/storage/tmp/sprint2-sample.mp4 >/tmp/ffmpeg-sample.log 2>&1"

docker compose exec api pytest tests/integration/test_sprint2_acceptance.py -q -rA

Write-Host "Running worker restart acceptance..."

$login = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/auth/login" -Method Post -ContentType "application/json" -Body (@{
  email = "editor@example.com"
  password = "editor123"
} | ConvertTo-Json)

$headers = @{ Authorization = "Bearer $($login.access_token)" }

$project = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/projects" -Method Post -Headers $headers -ContentType "application/json" -Body (@{
  name = "Sprint 2 Restart Acceptance"
  source_language = "en"
  target_language = "tr"
} | ConvertTo-Json)

curl.exe -s -X POST -H "Authorization: Bearer $($login.access_token)" -F "file=@C:\xampp\htdocs\AIDublajStudio\storage\tmp\sprint2-sample.mp4;type=video/mp4" "http://localhost:8000/api/v1/projects/$($project.id)/upload" | Out-Null

$detail = $null
for ($i = 0; $i -lt 30; $i++) {
  Start-Sleep -Seconds 2
  $detail = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/projects/$($project.id)" -Method Get -Headers $headers
  if ($detail.jobs.Count -gt 0 -and $detail.jobs[0].state -eq "COMPLETED") {
    break
  }
}

if ($detail.jobs[0].state -ne "COMPLETED") {
  throw "Media job did not complete before worker restart test."
}

$artifactCountBefore = $detail.artifacts.Count
$jobId = $detail.jobs[0].id

docker compose restart worker-media
Start-Sleep -Seconds 8

$detailAfterRestart = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/projects/$($project.id)" -Method Get -Headers $headers
if ($detailAfterRestart.jobs[0].id -ne $jobId) {
  throw "Unexpected job change after worker restart."
}
if ($detailAfterRestart.jobs[0].state -ne "COMPLETED") {
  throw "Completed job changed state after worker restart."
}
if ($detailAfterRestart.artifacts.Count -ne $artifactCountBefore) {
  throw "Completed job produced duplicate artifacts after worker restart."
}

Write-Host "Running processing recovery acceptance..."

$recoveryProject = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/projects" -Method Post -Headers $headers -ContentType "application/json" -Body (@{
  name = "Sprint 2 Recovery Acceptance"
  source_language = "en"
  target_language = "tr"
} | ConvertTo-Json)

curl.exe -s -X POST -H "Authorization: Bearer $($login.access_token)" -F "file=@C:\xampp\htdocs\AIDublajStudio\storage\tmp\sprint2-sample.mp4;type=video/mp4" "http://localhost:8000/api/v1/projects/$($recoveryProject.id)/upload" | Out-Null

$recoveryDetail = $null
for ($i = 0; $i -lt 10; $i++) {
  Start-Sleep -Seconds 1
  $recoveryDetail = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/projects/$($recoveryProject.id)" -Method Get -Headers $headers
  if ($recoveryDetail.jobs.Count -gt 0) {
    break
  }
}

$recoveryJobId = $recoveryDetail.jobs[0].id
docker exec aidublaj-postgres psql -U aidublaj -d aidublaj -c "update jobs set state='PROCESSING', worker_name='worker-media', started_at=now(), completed_at=null, updated_at=now() where id='$recoveryJobId';"

docker compose restart worker-media

for ($i = 0; $i -lt 30; $i++) {
  Start-Sleep -Seconds 2
  $recoveryDetail = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/projects/$($recoveryProject.id)" -Method Get -Headers $headers
  if ($recoveryDetail.jobs[0].state -eq "COMPLETED") {
    break
  }
}

if ($recoveryDetail.jobs[0].state -ne "COMPLETED") {
  throw "Recovered processing job did not return to COMPLETED."
}

Write-Host "Sprint 2 acceptance tests passed."
