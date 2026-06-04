$ErrorActionPreference = "Stop"

Set-Location "C:\xampp\htdocs\AIDublajStudio"

$env:ASR_PROVIDER = "mock"
$env:TRANSLATION_PROVIDER = "mock"
$env:DIARIZATION_PROVIDER = "mock"
$env:TTS_PROVIDER = "mock"
$env:VOICE_CLONE_PROVIDER = "cosyvoice"
$env:COSYVOICE_SERVICE_URL = "http://cosyvoice-service:8010"
$env:VOICE_CLONE_MIN_SAMPLE_DURATION_MS = "500"

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

function Wait-ForCosyVoiceService {
  param([int]$Attempts = 600, [int]$DelaySeconds = 2)
  for ($i = 0; $i -lt $Attempts; $i++) {
    try {
      $response = Invoke-RestMethod -Uri "http://localhost:8010/health" -Method Get
      if ($response.status -eq "ok") {
        if (-not $response.configured) {
          if ($response.error) {
            throw "CosyVoice service is running but not configured: $($response.error)"
          }
          throw "CosyVoice service is running but not configured."
        }
        return
      }
    } catch {
      Start-Sleep -Seconds $DelaySeconds
    }
  }
  throw "CosyVoice service did not become ready in time."
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

  if (-not $env:COSYVOICE_SYNTH_COMMAND -and (-not $env:COSYVOICE_MODEL_DIR -or -not $env:COSYVOICE_REPO_DIR)) {
    throw "Set COSYVOICE_SYNTH_COMMAND or provide COSYVOICE_REPO_DIR and COSYVOICE_MODEL_DIR before running Sprint 19 CosyVoice smoke test."
  }

  $projectsPath = "C:\xampp\htdocs\AIDublajStudio\storage\projects"
  Get-ChildItem $projectsPath -Force | Where-Object { $_.Name -ne ".gitkeep" } | Remove-Item -Recurse -Force

  docker compose --profile app --profile cosyvoice down -v --remove-orphans
  Assert-LastExitCode "docker compose down"
  docker compose --profile app --profile cosyvoice up -d --build
  Assert-LastExitCode "docker compose up"

  Wait-ForApi
  Wait-ForCosyVoiceService

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
r = s.post(f"{base}/projects", headers=headers, json={"name": "Sprint 19 CosyVoice Smoke", "source_language": "en", "target_language": "tr"})
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

wait_for("DIARIZE", "COMPLETED")
r = s.post(f"{base}/projects/{project_id}/characters/from-speakers", headers=headers)
r.raise_for_status()
detail = r.json()
character_id = detail["characters"][0]["id"]
clip = next(item for item in detail["timeline_clips"] if item["character_id"] == character_id)
r = s.patch(
    f"{base}/projects/{project_id}/timeline/clips/{clip['id']}",
    headers=headers,
    json={"translation_text": "Merhaba John.", "character_id": character_id},
)
r.raise_for_status()
r = s.post(f"{base}/projects/{project_id}/characters/{character_id}/voice-sample", headers=headers)
r.raise_for_status()
wait_for("VOICE_SAMPLE_EXTRACT", "COMPLETED")
r = s.post(f"{base}/projects/{project_id}/characters/{character_id}/voice-profile/from-sample", headers=headers)
r.raise_for_status()
detail = r.json()
character = next(item for item in detail["characters"] if item["id"] == character_id)
reference_audio_artifact_id = character["assigned_voice_profile"]["reference_audio_artifact_id"]
r = s.post(f"{base}/projects/{project_id}/tts", headers=headers)
r.raise_for_status()
detail = wait_for("TTS", "COMPLETED")
segment = next(item for item in detail["dub_segments"] if item["character_id"] == character_id)
assert segment["provider"] == "cosyvoice", segment
assert segment["metadata_json"]["cloned"] is True, segment
assert segment["metadata_json"]["reference_audio_artifact_id"] == reference_audio_artifact_id, segment
assert segment["metadata_json"]["model_name"], segment
r = s.post(f"{base}/projects/{project_id}/audio-mix", headers=headers)
r.raise_for_status()
wait_for("AUDIO_MIX", "COMPLETED")
r = s.post(f"{base}/projects/{project_id}/render", headers=headers)
r.raise_for_status()
detail = wait_for("RENDER", "COMPLETED")
print(json.dumps({
    "project_id": project_id,
    "tts_provider": segment["provider"],
    "model_name": segment["metadata_json"]["model_name"],
    "reference_audio_artifact_id": reference_audio_artifact_id,
    "render_artifact": next(artifact["id"] for artifact in detail["artifacts"] if artifact["artifact_type"] == "FINAL_RENDER"),
}))
'@ | docker compose exec -T api python -
  Assert-LastExitCode "cosyvoice success smoke"

  docker compose --profile app --profile cosyvoice down -v --remove-orphans
  Assert-LastExitCode "docker compose down (failure cases)"
  docker compose --profile app --profile cosyvoice up -d --build
  Assert-LastExitCode "docker compose up (failure cases)"
  Wait-ForApi
  Wait-ForCosyVoiceService

  @'
import json
import pathlib
import time

import psycopg
import requests

base = "http://host.docker.internal:8000/api/v1"
database_url = "postgresql://aidublaj:aidublaj@postgres:5432/aidublaj"
s = requests.Session()
r = s.post(f"{base}/auth/login", json={"email": "editor@example.com", "password": "editor123"})
r.raise_for_status()
token = r.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}

def create_project(name: str):
    response = s.post(f"{base}/projects", headers=headers, json={"name": name, "source_language": "en", "target_language": "tr"})
    response.raise_for_status()
    return response.json()["id"]

def upload_and_prepare(project_id: str):
    sample = pathlib.Path("/workspace/storage/tmp/sprint2-sample.mp4")
    with sample.open("rb") as handle:
        response = s.post(f"{base}/projects/{project_id}/upload", headers=headers, files={"file": (sample.name, handle, "video/mp4")})
        response.raise_for_status()

def wait_for(project_id: str, job_type: str, state: str, attempts: int = 90):
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

def prepare_character(project_id: str):
    wait_for(project_id, "DIARIZE", "COMPLETED")
    detail = s.post(f"{base}/projects/{project_id}/characters/from-speakers", headers=headers)
    detail.raise_for_status()
    payload = detail.json()
    character_id = payload["characters"][0]["id"]
    clip = next(item for item in payload["timeline_clips"] if item["character_id"] == character_id)
    patch = s.patch(
        f"{base}/projects/{project_id}/timeline/clips/{clip['id']}",
        headers=headers,
        json={"translation_text": "Merhaba John.", "character_id": character_id},
    )
    patch.raise_for_status()
    return character_id

with psycopg.connect(database_url) as conn:
    project_id = create_project("Sprint 19 Missing Reference")
    upload_and_prepare(project_id)
    character_id = prepare_character(project_id)
    s.post(f"{base}/projects/{project_id}/characters/{character_id}/voice-sample", headers=headers).raise_for_status()
    wait_for(project_id, "VOICE_SAMPLE_EXTRACT", "COMPLETED")
    detail = s.post(f"{base}/projects/{project_id}/characters/{character_id}/voice-profile/from-sample", headers=headers)
    detail.raise_for_status()
    payload = detail.json()
    voice_profile_id = next(item for item in payload["characters"] if item["id"] == character_id)["assigned_voice_profile_id"]
    conn.execute("update voice_profiles set reference_audio_artifact_id = null where id = %s", (voice_profile_id,))
    conn.commit()
    s.post(f"{base}/projects/{project_id}/tts", headers=headers).raise_for_status()
    failed = wait_for(project_id, "TTS", "FAILED")
    job = next(job for job in failed["jobs"] if job["job_type"] == "TTS")
    assert job["error_json"], job

    project_id = create_project("Sprint 19 Short Sample")
    upload_and_prepare(project_id)
    character_id = prepare_character(project_id)
    s.post(f"{base}/projects/{project_id}/characters/{character_id}/voice-sample", headers=headers).raise_for_status()
    wait_for(project_id, "VOICE_SAMPLE_EXTRACT", "COMPLETED")
    detail = s.post(f"{base}/projects/{project_id}/characters/{character_id}/voice-profile/from-sample", headers=headers)
    detail.raise_for_status()
    payload = detail.json()
    character = next(item for item in payload["characters"] if item["id"] == character_id)
    voice_profile_id = character["assigned_voice_profile_id"]
    reference_audio_artifact_id = character["assigned_voice_profile"]["reference_audio_artifact_id"]
    conn.execute("update voice_profiles set sample_duration_ms = 200 where id = %s", (voice_profile_id,))
    conn.execute("update artifacts set duration_ms = 200 where id = %s", (reference_audio_artifact_id,))
    conn.commit()
    s.post(f"{base}/projects/{project_id}/tts", headers=headers).raise_for_status()
    failed = wait_for(project_id, "TTS", "FAILED")
    job = next(job for job in failed["jobs"] if job["job_type"] == "TTS")
    assert "VOICE_REFERENCE_TOO_SHORT" in json.dumps(job["error_json"]), job

print(json.dumps({
    "missing_reference_tts_state": "FAILED",
    "short_sample_tts_state": "FAILED",
}))
'@ | docker compose exec -T api python -
  Assert-LastExitCode "cosyvoice failure smoke"

  Write-Host "Sprint 19 CosyVoice smoke tests passed."
} finally {
  if (Test-DockerAvailable) {
    try {
      docker compose --profile app --profile cosyvoice down -v --remove-orphans
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
