param(
  [ValidateSet("en", "sr", "auto")]
  [string]$Language = "en",
  [string]$SampleVideoPath = "",
  [switch]$SkipFailureCase
)

$ErrorActionPreference = "Stop"

Set-Location "C:\xampp\htdocs\AIDublajStudio"

function Wait-ForApi {
  for ($i = 0; $i -lt 90; $i++) {
    try {
      $response = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/health" -Method Get
      if ($response.status -eq "ok") { return }
    } catch {
      Start-Sleep -Seconds 2
    }
  }
  throw "API did not become healthy."
}

function Wait-ForWorkerMediaFfmpeg {
  for ($i = 0; $i -lt 120; $i++) {
    try {
      docker exec aidublaj-worker-media-dev sh -c "ffmpeg -version >/dev/null 2>&1"
      if ($LASTEXITCODE -eq 0) { return }
    } catch {
    }
    Start-Sleep -Seconds 2
  }
  throw "worker-media ffmpeg is not ready."
}

function Invoke-Login {
  return Invoke-RestMethod -Uri "http://localhost:8000/api/v1/auth/login" -Method Post -ContentType "application/json" -Body (@{
    email = "editor@example.com"
    password = "editor123"
  } | ConvertTo-Json)
}

function New-SampleVideo {
  param(
    [string]$TargetVideoPath,
    [string]$SourceLanguage
  )

  if ($SampleVideoPath) {
    Copy-Item -LiteralPath $SampleVideoPath -Destination $TargetVideoPath -Force
    return
  }

  if ($SourceLanguage -ne "en" -and $SourceLanguage -ne "auto") {
    throw "SampleVideoPath is required for non-English smoke tests."
  }

  $tmpDir = Split-Path -Parent $TargetVideoPath
  New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null
  $wavPath = Join-Path $tmpDir "faster-whisper-sample.wav"

  $voice = New-Object -ComObject SAPI.SpVoice
  $stream = New-Object -ComObject SAPI.SpFileStream
  $stream.Open($wavPath, 3, $false)
  $voice.AudioOutputStream = $stream
  [void]$voice.Speak("Hello this is a faster whisper smoke test for AI dublaj studio.")
  $stream.Close()

  docker exec aidublaj-worker-media-dev sh -c "ffmpeg -y -f lavfi -i color=c=black:s=640x360:d=6 -i /workspace/storage/tmp/faster-whisper-sample.wav -shortest -c:v libx264 -pix_fmt yuv420p -c:a aac /workspace/storage/tmp/faster-whisper-sample.mp4 >/tmp/ffmpeg-fw-smoke.log 2>&1"
  Move-Item -LiteralPath "C:\xampp\htdocs\AIDublajStudio\storage\tmp\faster-whisper-sample.mp4" -Destination $TargetVideoPath -Force
}

function Wait-ForTranscribeResult {
  param(
    [string]$ProjectId,
    [hashtable]$Headers,
    [string]$ExpectedState
  )

  for ($i = 0; $i -lt 120; $i++) {
    $detail = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/projects/$ProjectId" -Method Get -Headers $Headers
    $jobsByType = @{}
    foreach ($job in $detail.jobs) { $jobsByType[$job.job_type] = $job }
    if ($jobsByType.ContainsKey("TRANSCRIBE") -and $jobsByType["TRANSCRIBE"].state -eq $ExpectedState) {
      return $detail
    }
    Start-Sleep -Seconds 2
  }
  throw "TRANSCRIBE job did not reach $ExpectedState for project $ProjectId."
}

$env:ASR_PROVIDER = "faster_whisper"
$env:ASR_SOURCE_LANGUAGE = $Language
$env:ASR_MODEL_SIZE = "tiny"
$env:ASR_DEVICE = "auto"
$env:ASR_COMPUTE_TYPE = "auto"

$projectsPath = "C:\xampp\htdocs\AIDublajStudio\storage\projects"
Get-ChildItem $projectsPath -Force | Where-Object { $_.Name -ne ".gitkeep" } | Remove-Item -Recurse -Force
New-Item -ItemType Directory -Force -Path "C:\xampp\htdocs\AIDublajStudio\storage\tmp" | Out-Null

docker compose --profile app down -v --remove-orphans
docker compose --profile app up -d --build
Wait-ForApi
Wait-ForWorkerMediaFfmpeg

$videoPath = "C:\xampp\htdocs\AIDublajStudio\storage\tmp\sprint4-faster-whisper-smoke.mp4"
New-SampleVideo -TargetVideoPath $videoPath -SourceLanguage $Language

$login = Invoke-Login
$headers = @{ Authorization = "Bearer $($login.access_token)" }

$project = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/projects" -Method Post -Headers $headers -ContentType "application/json" -Body (@{
  name = "Sprint 4 Faster Whisper Smoke"
  source_language = $Language
  target_language = "tr"
} | ConvertTo-Json)

curl.exe -s -X POST -H "Authorization: Bearer $($login.access_token)" -F "file=@$videoPath;type=video/mp4" "http://localhost:8000/api/v1/projects/$($project.id)/upload" | Out-Null

$detail = Wait-ForTranscribeResult -ProjectId $project.id -Headers $headers -ExpectedState "COMPLETED"
$jobsByType = @{}
foreach ($job in $detail.jobs) { $jobsByType[$job.job_type] = $job }

if ($detail.transcript_segments.Count -lt 1) {
  throw "No transcript segments were created."
}
if ($detail.timeline_clips.Count -lt 1) {
  throw "No timeline clips were created."
}
if ($jobsByType["TRANSCRIBE"].output_json.provider -ne "faster_whisper") {
  throw "Unexpected provider in output_json."
}

$transcriptText = (($detail.transcript_segments | ForEach-Object { $_.text }) -join " ").ToLowerInvariant()
if (($Language -eq "en" -or $Language -eq "auto") -and ($transcriptText -notmatch "hello|smoke|studio")) {
  throw "Transcript text does not look like real English transcription: $transcriptText"
}

Write-Host "Faster-Whisper smoke success passed."

if (-not $SkipFailureCase) {
  $env:ASR_MODEL_SIZE = "definitely-invalid-model"
  docker compose --profile app up -d --build --force-recreate api worker-gpu-0
  Wait-ForApi

  $failureProject = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/projects" -Method Post -Headers $headers -ContentType "application/json" -Body (@{
    name = "Sprint 4 Faster Whisper Failure"
    source_language = $Language
    target_language = "tr"
  } | ConvertTo-Json)

  curl.exe -s -X POST -H "Authorization: Bearer $($login.access_token)" -F "file=@$videoPath;type=video/mp4" "http://localhost:8000/api/v1/projects/$($failureProject.id)/upload" | Out-Null

  $failedDetail = Wait-ForTranscribeResult -ProjectId $failureProject.id -Headers $headers -ExpectedState "FAILED"
  $failedJobs = @{}
  foreach ($job in $failedDetail.jobs) { $failedJobs[$job.job_type] = $job }
  if (-not $failedJobs["TRANSCRIBE"].state.Equals("FAILED")) {
    throw "Expected failed transcribe job during provider failure case."
  }
  Write-Host "Faster-Whisper failure smoke passed."
}
