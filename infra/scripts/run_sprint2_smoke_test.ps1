$ErrorActionPreference = "Stop"

Set-Location "C:\xampp\htdocs\AIDublajStudio"

docker exec aidublaj-worker-media-dev sh -c "mkdir -p /workspace/storage/tmp && ffmpeg -y -f lavfi -i color=c=black:s=320x240:d=1 -f lavfi -i anullsrc=r=44100:cl=mono -shortest -c:v libx264 -pix_fmt yuv420p -c:a aac /workspace/storage/tmp/sprint2-sample.mp4 >/tmp/ffmpeg-sample.log 2>&1"

$login = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/auth/login" -Method Post -ContentType "application/json" -Body (@{
  email = "editor@example.com"
  password = "editor123"
} | ConvertTo-Json)

$headers = @{ Authorization = "Bearer $($login.access_token)" }

$project = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/projects" -Method Post -Headers $headers -ContentType "application/json" -Body (@{
  name = "Sprint 2 Smoke Test"
  source_language = "en"
  target_language = "tr"
} | ConvertTo-Json)

curl.exe -s -X POST -H "Authorization: Bearer $($login.access_token)" -F "file=@C:\xampp\htdocs\AIDublajStudio\storage\tmp\sprint2-sample.mp4;type=video/mp4" "http://localhost:8000/api/v1/projects/$($project.id)/upload" | Out-Null

$detail = $null
for ($i = 0; $i -lt 30; $i++) {
  Start-Sleep -Seconds 2
  $detail = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/projects/$($project.id)" -Method Get -Headers $headers
  $artifactTypes = @($detail.artifacts | ForEach-Object { $_.artifact_type })
  if (
    $artifactTypes -contains "VIDEO_METADATA" -and
    $artifactTypes -contains "THUMBNAIL" -and
    $artifactTypes -contains "PROXY_VIDEO" -and
    $artifactTypes -contains "WAVEFORM_JSON"
  ) {
    break
  }
}

$finalTypes = @($detail.artifacts | ForEach-Object { $_.artifact_type })
if (
  -not ($finalTypes -contains "VIDEO_METADATA") -or
  -not ($finalTypes -contains "THUMBNAIL") -or
  -not ($finalTypes -contains "PROXY_VIDEO") -or
  -not ($finalTypes -contains "WAVEFORM_JSON")
) {
  throw "Sprint 2 media artifacts were not all produced."
}

Write-Host "Sprint 2 smoke test passed."
