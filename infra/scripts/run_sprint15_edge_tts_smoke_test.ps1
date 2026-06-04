$ErrorActionPreference = "Stop"

Set-Location "C:\xampp\htdocs\AIDublajStudio"

$env:ASR_PROVIDER = "mock"
$env:TRANSLATION_PROVIDER = "mock"
$env:DIARIZATION_PROVIDER = "mock"
$env:TTS_PROVIDER = "edge_tts"
$env:EDGE_TTS_VOICE = "tr-TR-AhmetNeural"
$env:TTS_VOICE_NAME = "default"

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

function Wait-ForWorkerMediaFfmpeg {
  param([int]$Attempts = 60, [int]$DelaySeconds = 2)
  for ($i = 0; $i -lt $Attempts; $i++) {
    docker compose exec -T worker-media sh -c "command -v ffmpeg >/dev/null 2>&1"
    if ($LASTEXITCODE -eq 0) { return }
    Start-Sleep -Seconds $DelaySeconds
  }
  throw "worker-media ffmpeg did not become ready in time."
}

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

  Wait-ForApi

  $sampleVideoHostPath = "C:\xampp\htdocs\AIDublajStudio\storage\tmp\sprint2-sample.mp4"
  if (-not (Test-Path $sampleVideoHostPath)) {
    Wait-ForWorkerMediaFfmpeg
    docker compose exec -T worker-media sh -c "mkdir -p /workspace/storage/tmp && ffmpeg -y -f lavfi -i color=c=black:s=320x240:d=4 -f lavfi -i sine=frequency=880:duration=4 -shortest -c:v libx264 -pix_fmt yuv420p -c:a aac /workspace/storage/tmp/sprint2-sample.mp4 >/tmp/ffmpeg-sample.log 2>&1"
    Assert-LastExitCode "worker-media sample video generation"
  }

  @'
import json
import pathlib
import time
import requests

base = "http://host.docker.internal:8000/api/v1"
s = requests.Session()
r = s.post(f"{base}/auth/login", json={"email": "editor@example.com", "password": "editor123"})
r.raise_for_status()
token = r.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}
r = s.post(f"{base}/projects", headers=headers, json={"name": "Sprint 15 Edge TTS Smoke", "source_language": "en", "target_language": "tr"})
r.raise_for_status()
project_id = r.json()["id"]
sample = pathlib.Path("/workspace/storage/tmp/sprint2-sample.mp4")
with sample.open("rb") as handle:
    r = s.post(f"{base}/projects/{project_id}/upload", headers=headers, files={"file": (sample.name, handle, "video/mp4")})
    r.raise_for_status()

def wait_for(job_type: str, state: str, attempts: int = 90):
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

wait_for("TRANSLATE", "COMPLETED")
r = s.post(f"{base}/projects/{project_id}/tts", headers=headers)
r.raise_for_status()
detail = wait_for("TTS", "COMPLETED")
r = s.post(f"{base}/projects/{project_id}/audio-mix", headers=headers)
r.raise_for_status()
detail = wait_for("AUDIO_MIX", "COMPLETED")
r = s.post(f"{base}/projects/{project_id}/render", headers=headers)
r.raise_for_status()
detail = wait_for("RENDER", "COMPLETED")
tts_artifact = next(artifact for artifact in detail["artifacts"] if artifact["artifact_type"] == "TTS_AUDIO")
mix_artifact = next(artifact for artifact in detail["artifacts"] if artifact["artifact_type"] == "FINAL_DUB_AUDIO")
render_artifact = next(artifact for artifact in detail["artifacts"] if artifact["artifact_type"] == "FINAL_RENDER")
print(json.dumps({
    "project_id": project_id,
    "tts_file": tts_artifact["file_name"],
    "tts_path": tts_artifact["storage_path"],
    "mix_file": mix_artifact["file_name"],
    "render_file": render_artifact["file_name"],
    "jobs": {job["job_type"]: job["state"] for job in detail["jobs"] if job["job_type"] in ["TTS", "AUDIO_MIX", "RENDER"]},
}))
'@ | docker compose exec -T api python -
  Assert-LastExitCode "edge_tts success smoke"

$env:EDGE_TTS_VOICE = "tr-TR-AhmetNeural"
  docker compose --profile app down -v --remove-orphans
  Assert-LastExitCode "docker compose down (failure case)"
  docker compose --profile app up -d --build
  Assert-LastExitCode "docker compose up (failure case)"

  Wait-ForApi

  @'
import json
import pathlib
import time
import requests

base = "http://host.docker.internal:8000/api/v1"
s = requests.Session()
r = s.post(f"{base}/auth/login", json={"email": "editor@example.com", "password": "editor123"})
r.raise_for_status()
token = r.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}
r = s.post(f"{base}/projects", headers=headers, json={"name": "Sprint 15 Edge TTS Failure", "source_language": "en", "target_language": "tr"})
r.raise_for_status()
project_id = r.json()["id"]
sample = pathlib.Path("/workspace/storage/tmp/sprint2-sample.mp4")
with sample.open("rb") as handle:
    r = s.post(f"{base}/projects/{project_id}/upload", headers=headers, files={"file": (sample.name, handle, "video/mp4")})
    r.raise_for_status()

def wait_for(job_type: str, state: str, attempts: int = 90):
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

wait_for("TRANSLATE", "COMPLETED")
r = s.post(f"{base}/projects/{project_id}/characters/from-speakers", headers=headers)
r.raise_for_status()
detail = r.json()
character_id = detail["characters"][0]["id"]
r = s.post(
    f"{base}/voice-profiles",
    headers=headers,
    json={
        "display_name": "Invalid Edge Voice",
        "description": "Failure smoke profile",
        "provider": "edge_tts",
        "voice_id": "invalid-voice-name",
        "language": "tr",
        "gender": "unknown",
        "is_shared": False,
        "metadata_json": {"failure_case": True},
    },
)
r.raise_for_status()
voice_profile_id = r.json()["id"]
r = s.post(
    f"{base}/projects/{project_id}/characters/{character_id}/voice-profile",
    headers=headers,
    json={"voice_profile_id": voice_profile_id},
)
r.raise_for_status()
r = s.post(f"{base}/projects/{project_id}/tts", headers=headers)
r.raise_for_status()
detail = wait_for("TTS", "FAILED")
job = next(job for job in detail["jobs"] if job["job_type"] == "TTS")
assert job["state"] == "FAILED"
assert job["error_json"]
print(json.dumps({
    "project_id": project_id,
    "voice_profile_id": voice_profile_id,
    "tts_state": job["state"],
    "error": job["error_json"],
}))
'@ | docker compose exec -T api python -
  Assert-LastExitCode "edge_tts failure smoke"

  Write-Host "Sprint 15 Edge TTS smoke tests passed."
} finally {
  if (Test-DockerAvailable) {
    try {
      docker compose --profile app down -v --remove-orphans
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
