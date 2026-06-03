$ErrorActionPreference = "Stop"

Set-Location "C:\xampp\htdocs\AIDublajStudio"

$loginBody = @{
  email = "editor@example.com"
  password = "editor123"
} | ConvertTo-Json

$token = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/auth/login" -Method Post -ContentType "application/json" -Body $loginBody
$headers = @{ Authorization = "Bearer $($token.access_token)" }

$project = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/projects" -Method Post -Headers $headers -ContentType "application/json" -Body (@{
  name = "Restart Resume Test"
  source_language = "en"
  target_language = "tr"
} | ConvertTo-Json)

$tempFile = Join-Path $env:TEMP "restart-test.mp4"
[System.IO.File]::WriteAllBytes($tempFile, [System.Text.Encoding]::UTF8.GetBytes("fake mp4 payload"))

curl.exe -s -X POST -H "Authorization: Bearer $($token.access_token)" -F "file=@$tempFile;type=video/mp4" "http://localhost:8000/api/v1/projects/$($project.id)/upload" | Out-Null

docker compose restart api
Start-Sleep -Seconds 5

$detail = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/projects/$($project.id)" -Method Get -Headers $headers

if ($detail.jobs.Count -lt 1) {
  throw "Job was lost after API restart."
}

Write-Host "Restart/resume test passed."
