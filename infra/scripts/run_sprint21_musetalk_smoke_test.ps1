$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $repoRoot

$dockerBin = "C:\Program Files\Docker\Docker\resources\bin"
if ((Test-Path $dockerBin) -and ($env:Path -notlike "*$dockerBin*")) {
  $env:Path = "$dockerBin;$env:Path"
}

$env:ASR_PROVIDER = "mock"
$env:TRANSLATION_PROVIDER = "mock"
$env:DIARIZATION_PROVIDER = "mock"
$env:TTS_PROVIDER = "mock"
$env:VOICE_CLONE_PROVIDER = "mock"
$env:LIP_SYNC_PROVIDER = "musetalk"
$env:MUSETALK_SERVICE_URL = "http://musetalk-service:8020"
if (-not $env:MUSETALK_SERVICE_TIMEOUT_SECONDS) { $env:MUSETALK_SERVICE_TIMEOUT_SECONDS = "1800" }
if (-not $env:MUSETALK_BOOTSTRAP) { $env:MUSETALK_BOOTSTRAP = "1" }
if (-not $env:MUSETALK_REPO_URL) { $env:MUSETALK_REPO_URL = "https://github.com/TMElyralab/MuseTalk.git" }
if (-not $env:MUSETALK_REPO_DIR) { $env:MUSETALK_REPO_DIR = "/opt/musetalk/MuseTalk" }
if (-not $env:MUSETALK_MODEL_DIR) { $env:MUSETALK_MODEL_DIR = "/opt/musetalk/MuseTalk/models" }
if (-not $env:MUSETALK_DEVICE) { $env:MUSETALK_DEVICE = "auto" }
if (-not $env:MUSETALK_INSTALL_MODE) { $env:MUSETALK_INSTALL_MODE = "minimal" }
if (-not $env:MUSETALK_BATCH_SIZE) { $env:MUSETALK_BATCH_SIZE = "2" }

function Test-DockerAvailable {
  try {
    docker version | Out-Null
    return $true
  } catch {
    return $false
  }
}

function Assert-LastExitCode {
  param([string]$CommandName)
  if ($LASTEXITCODE -ne 0) {
    throw "$CommandName failed with exit code $LASTEXITCODE."
  }
}

function Wait-ForApi {
  param([int]$Attempts = 120, [int]$DelaySeconds = 2)
  for ($i = 0; $i -lt $Attempts; $i++) {
    try {
      $response = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/health" -Method Get
      if ($response.status -eq "ok") { return }
    } catch {
      Start-Sleep -Seconds $DelaySeconds
    }
  }
  throw "API did not become healthy in time."
}

function Wait-ForMuseTalkService {
  param([int]$Attempts = 900, [int]$DelaySeconds = 2)
  for ($i = 0; $i -lt $Attempts; $i++) {
    $response = $null
    try {
      $response = Invoke-RestMethod -Uri "http://localhost:8020/health" -Method Get
    } catch {
      Start-Sleep -Seconds $DelaySeconds
      continue
    }
    if ($response.status -eq "ok") {
      if ($response.configured) { return }
      if ($response.error) {
        throw "MuseTalk service is running but not configured: $($response.error)"
      }
    }
    Start-Sleep -Seconds $DelaySeconds
  }
  throw "MuseTalk service did not become ready in time."
}

$cleanupStatus = "Cleanup skipped."

try {
  if (-not (Test-DockerAvailable)) {
    throw "Docker daemon is not available."
  }

  $projectsPath = Join-Path $repoRoot "storage\projects"
  Get-ChildItem $projectsPath -Force | Where-Object { $_.Name -ne ".gitkeep" } | Remove-Item -Recurse -Force

  $sampleVideoHostPath = Join-Path $repoRoot "storage\tmp\sprint21-musetalk-face.mp4"
  New-Item -ItemType Directory -Force (Split-Path $sampleVideoHostPath) | Out-Null
  if (-not (Test-Path $sampleVideoHostPath)) {
    Invoke-WebRequest `
      -Uri "https://raw.githubusercontent.com/OpenTalker/video-retalking/main/examples/face/1.mp4" `
      -OutFile $sampleVideoHostPath
  }

  docker compose --profile app --profile musetalk down --remove-orphans
  Assert-LastExitCode "docker compose down"
  docker compose --profile app --profile musetalk up -d --build
  Assert-LastExitCode "docker compose up"

  Wait-ForApi
  Wait-ForMuseTalkService

  @'
import json
import pathlib
import time
import requests

base = "http://host.docker.internal:8000/api/v1"
s = requests.Session()
r = s.post(f"{base}/auth/login", json={"email": "editor@example.com", "password": "editor123"})
r.raise_for_status()
headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

def wait_for(project_id: str, job_type: str, state: str, attempts: int = 1200):
    payload = None
    for _ in range(attempts):
        detail = s.get(f"{base}/projects/{project_id}", headers=headers)
        detail.raise_for_status()
        payload = detail.json()
        jobs = {job["job_type"]: job for job in payload["jobs"]}
        if job_type in jobs and jobs[job_type]["state"] == state:
            return payload
        if job_type in jobs and jobs[job_type]["state"] == "FAILED" and state != "FAILED":
            raise RuntimeError(f"{job_type} failed: {json.dumps(jobs[job_type].get('error_json'), ensure_ascii=False)}")
        time.sleep(2)
    raise RuntimeError(f"timeout waiting for {job_type}={state}")

def prepare_project(name: str):
    r = s.post(f"{base}/projects", headers=headers, json={"name": name, "source_language": "en", "target_language": "tr"})
    r.raise_for_status()
    project_id = r.json()["id"]
    sample = pathlib.Path("/workspace/storage/tmp/sprint21-musetalk-face.mp4")
    with sample.open("rb") as handle:
        r = s.post(f"{base}/projects/{project_id}/upload", headers=headers, files={"file": (sample.name, handle, "video/mp4")})
        r.raise_for_status()
    wait_for(project_id, "DIARIZE", "COMPLETED")
    r = s.post(f"{base}/projects/{project_id}/tts", headers=headers)
    r.raise_for_status()
    wait_for(project_id, "TTS", "COMPLETED")
    r = s.post(f"{base}/projects/{project_id}/audio-mix", headers=headers)
    r.raise_for_status()
    wait_for(project_id, "AUDIO_MIX", "COMPLETED")
    return project_id

project_id = prepare_project("Sprint 21 MuseTalk Smoke")
r = s.post(f"{base}/projects/{project_id}/lip-sync", headers=headers)
r.raise_for_status()
detail = wait_for(project_id, "LIP_SYNC", "COMPLETED")
lipsync = next(artifact for artifact in detail["artifacts"] if artifact["artifact_type"] == "LIPSYNC_VIDEO")
final_audio = next(artifact for artifact in detail["artifacts"] if artifact["artifact_type"] == "FINAL_DUB_AUDIO")
assert lipsync["metadata_json"]["provider"] == "musetalk", lipsync
assert lipsync["metadata_json"]["lip_sync_provider"]["mock"] is False, lipsync
assert final_audio["id"] in lipsync["parent_artifact_ids"], lipsync
path = pathlib.Path("/workspace/storage/projects") / lipsync["storage_path"]
assert path.exists(), path
assert path.stat().st_size > 0, path
print(json.dumps({
    "project_id": project_id,
    "lipsync_artifact_id": lipsync["id"],
    "final_dub_audio_artifact_id": final_audio["id"],
    "provider": lipsync["metadata_json"]["provider"],
    "mock": lipsync["metadata_json"]["lip_sync_provider"]["mock"],
}))
'@ | docker compose exec -T api python -
  Assert-LastExitCode "musetalk success smoke"

  docker compose stop musetalk-service
  Assert-LastExitCode "stop musetalk service"

  @'
import json
import pathlib
import time
import requests

base = "http://host.docker.internal:8000/api/v1"
s = requests.Session()
r = s.post(f"{base}/auth/login", json={"email": "editor@example.com", "password": "editor123"})
r.raise_for_status()
headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

def wait_for(project_id: str, job_type: str, state: str, attempts: int = 300):
    payload = None
    for _ in range(attempts):
        detail = s.get(f"{base}/projects/{project_id}", headers=headers)
        detail.raise_for_status()
        payload = detail.json()
        jobs = {job["job_type"]: job for job in payload["jobs"]}
        if job_type in jobs and jobs[job_type]["state"] == state:
            return payload
        time.sleep(2)
    raise RuntimeError(f"timeout waiting for {job_type}={state}")

r = s.post(f"{base}/projects", headers=headers, json={"name": "Sprint 21 MuseTalk Provider Failure", "source_language": "en", "target_language": "tr"})
r.raise_for_status()
project_id = r.json()["id"]
sample = pathlib.Path("/workspace/storage/tmp/sprint21-musetalk-face.mp4")
with sample.open("rb") as handle:
    r = s.post(f"{base}/projects/{project_id}/upload", headers=headers, files={"file": (sample.name, handle, "video/mp4")})
    r.raise_for_status()
wait_for(project_id, "DIARIZE", "COMPLETED")
s.post(f"{base}/projects/{project_id}/tts", headers=headers).raise_for_status()
wait_for(project_id, "TTS", "COMPLETED")
s.post(f"{base}/projects/{project_id}/audio-mix", headers=headers).raise_for_status()
wait_for(project_id, "AUDIO_MIX", "COMPLETED")
s.post(f"{base}/projects/{project_id}/lip-sync", headers=headers).raise_for_status()
detail = wait_for(project_id, "LIP_SYNC", "FAILED")
job = next(job for job in detail["jobs"] if job["job_type"] == "LIP_SYNC")
assert job["error_json"], job
health = s.get(f"{base}/health")
health.raise_for_status()
print(json.dumps({"provider_failure_lip_sync_state": "FAILED", "api_status": health.json()["status"]}))
'@ | docker compose exec -T api python -
  Assert-LastExitCode "musetalk provider failure smoke"

  Write-Host "Sprint 21 MuseTalk smoke tests passed."
} finally {
  if (Test-DockerAvailable) {
    try {
      docker compose --profile app --profile musetalk down --remove-orphans
      if ($LASTEXITCODE -eq 0) {
        $cleanupStatus = "Cleanup completed."
      } else {
        $cleanupStatus = "Cleanup failed: docker compose down exited with code $LASTEXITCODE."
      }
    } catch {
      $cleanupStatus = "Cleanup failed: $($_.Exception.Message)"
    }
  }
  Write-Host $cleanupStatus
}
