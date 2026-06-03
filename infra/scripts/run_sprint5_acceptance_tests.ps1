$ErrorActionPreference = "Stop"

Set-Location "C:\xampp\htdocs\AIDublajStudio"

$env:ASR_PROVIDER = "mock"
$env:TRANSLATION_PROVIDER = "mock"

$projectsPath = "C:\xampp\htdocs\AIDublajStudio\storage\projects"
Get-ChildItem $projectsPath -Force | Where-Object { $_.Name -ne ".gitkeep" } | Remove-Item -Recurse -Force

docker compose --profile app down -v --remove-orphans
docker compose --profile app up -d --build

Write-Host "Waiting for API..."
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

docker exec aidublaj-worker-media-dev sh -c "mkdir -p /workspace/storage/tmp && ffmpeg -y -f lavfi -i color=c=black:s=320x240:d=4 -f lavfi -i sine=frequency=880:duration=4 -shortest -c:v libx264 -pix_fmt yuv420p -c:a aac /workspace/storage/tmp/sprint2-sample.mp4 >/tmp/ffmpeg-sample.log 2>&1"

docker compose exec api pytest tests/integration/test_sprint5_acceptance.py -q -rA

Write-Host "Running completed translate restart acceptance..."

$login = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/auth/login" -Method Post -ContentType "application/json" -Body (@{
  email = "editor@example.com"
  password = "editor123"
} | ConvertTo-Json)

$headers = @{ Authorization = "Bearer $($login.access_token)" }

$project = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/projects" -Method Post -Headers $headers -ContentType "application/json" -Body (@{
  name = "Sprint 5 Restart Acceptance"
  source_language = "en"
  target_language = "tr"
} | ConvertTo-Json)

curl.exe -s -X POST -H "Authorization: Bearer $($login.access_token)" -F "file=@C:\xampp\htdocs\AIDublajStudio\storage\tmp\sprint2-sample.mp4;type=video/mp4" "http://localhost:8000/api/v1/projects/$($project.id)/upload" | Out-Null

$detail = $null
for ($i = 0; $i -lt 50; $i++) {
  Start-Sleep -Seconds 2
  $detail = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/projects/$($project.id)" -Method Get -Headers $headers
  $jobsByType = @{}
  foreach ($job in $detail.jobs) { $jobsByType[$job.job_type] = $job }
  if ($jobsByType.ContainsKey("TRANSLATE") -and $jobsByType["TRANSLATE"].state -eq "COMPLETED") {
    break
  }
}

if (-not $jobsByType.ContainsKey("TRANSLATE") -or $jobsByType["TRANSLATE"].state -ne "COMPLETED") {
  throw "Translate job did not complete before worker restart test."
}

$translateJobId = $jobsByType["TRANSLATE"].id
$translationCountBefore = $detail.translation_segments.Count

docker compose restart worker-gpu-0
Start-Sleep -Seconds 8

$detailAfterRestart = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/projects/$($project.id)" -Method Get -Headers $headers
$jobsAfterRestart = @{}
foreach ($job in $detailAfterRestart.jobs) { $jobsAfterRestart[$job.job_type] = $job }

if ($jobsAfterRestart["TRANSLATE"].id -ne $translateJobId) {
  throw "Unexpected translate job change after worker restart."
}
if ($jobsAfterRestart["TRANSLATE"].state -ne "COMPLETED") {
  throw "Completed translate job changed state after worker restart."
}
if ($detailAfterRestart.translation_segments.Count -ne $translationCountBefore) {
  throw "Completed translate job produced duplicate translation segments after worker restart."
}

Write-Host "Running translate processing recovery acceptance..."

$recoveryProject = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/projects" -Method Post -Headers $headers -ContentType "application/json" -Body (@{
  name = "Sprint 5 Recovery Acceptance"
  source_language = "en"
  target_language = "tr"
} | ConvertTo-Json)

curl.exe -s -X POST -H "Authorization: Bearer $($login.access_token)" -F "file=@C:\xampp\htdocs\AIDublajStudio\storage\tmp\sprint2-sample.mp4;type=video/mp4" "http://localhost:8000/api/v1/projects/$($recoveryProject.id)/upload" | Out-Null

$recoveryDetail = $null
for ($i = 0; $i -lt 50; $i++) {
  Start-Sleep -Seconds 2
  $recoveryDetail = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/projects/$($recoveryProject.id)" -Method Get -Headers $headers
  $recoveryJobs = @{}
  foreach ($job in $recoveryDetail.jobs) { $recoveryJobs[$job.job_type] = $job }
  if ($recoveryJobs.ContainsKey("TRANSLATE") -and $recoveryJobs["TRANSLATE"].state -eq "COMPLETED") {
    break
  }
}

$recoveryJobId = $recoveryJobs["TRANSLATE"].id
docker exec aidublaj-postgres psql -U aidublaj -d aidublaj -c "update jobs set state='PROCESSING', worker_name='worker-gpu-0', started_at=now(), completed_at=null, updated_at=now() where id='$recoveryJobId';"

docker compose restart worker-gpu-0

for ($i = 0; $i -lt 30; $i++) {
  Start-Sleep -Seconds 2
  $recoveryDetail = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/projects/$($recoveryProject.id)" -Method Get -Headers $headers
  $recoveryJobs = @{}
  foreach ($job in $recoveryDetail.jobs) { $recoveryJobs[$job.job_type] = $job }
  if ($recoveryJobs["TRANSLATE"].state -eq "COMPLETED") {
    break
  }
}

if ($recoveryJobs["TRANSLATE"].state -ne "COMPLETED") {
  throw "Recovered translate job did not return to COMPLETED."
}

Write-Host "Sprint 5 acceptance tests passed."
