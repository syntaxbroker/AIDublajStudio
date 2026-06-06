$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $repoRoot

$dockerBin = "C:\Program Files\Docker\Docker\resources\bin"
if ((Test-Path $dockerBin) -and ($env:Path -notlike "*$dockerBin*")) {
  $env:Path = "$dockerBin;$env:Path"
}

$manifestPath = if ($env:SPRINT29_MANIFEST_PATH) {
  $env:SPRINT29_MANIFEST_PATH
} else {
  Join-Path $repoRoot "storage\tmp\sprint29_inputs\manifest.json"
}

$outputPath = Join-Path $repoRoot "storage\tmp\sprint29_product_evaluation.json"
New-Item -ItemType Directory -Force (Split-Path $outputPath) | Out-Null

function Convert-ToContainerPath {
  param([string]$Path)
  $resolved = [System.IO.Path]::GetFullPath($Path)
  $root = [System.IO.Path]::GetFullPath($repoRoot)
  if ($resolved.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) {
    $relative = $resolved.Substring($root.Length).TrimStart("\", "/")
    return "/workspace/" + ($relative -replace "\\", "/")
  }
  return $resolved -replace "\\", "/"
}

$containerManifestPath = Convert-ToContainerPath $manifestPath
$containerOutputPath = Convert-ToContainerPath $outputPath

@'
import json
import os
import pathlib
import time
from datetime import datetime, timezone

import requests


BASE_URL = os.getenv("SPRINT29_API_BASE_URL", "http://host.docker.internal:8000/api/v1")
MANIFEST_PATH = pathlib.Path(os.environ["SPRINT29_MANIFEST_PATH"])
OUTPUT_PATH = pathlib.Path(os.environ["SPRINT29_OUTPUT_PATH"])
EXPECTED_PROVIDERS = {
    "ASR_PROVIDER": "faster_whisper",
    "TRANSLATION_PROVIDER": "ollama",
    "TTS_PROVIDER": "cosyvoice",
    "VOICE_CLONE_PROVIDER": "cosyvoice",
    "LIP_SYNC_PROVIDER": "musetalk",
}
CURRENT_PROVIDER_STATUS = None
VIDEOS_REQUIRED = 1
HUMAN_EVALUATION_TEMPLATE = {
    "asr_accuracy_1_10": None,
    "turkish_translation_naturalness_1_10": None,
    "voice_similarity_1_10": None,
    "voice_naturalness_1_10": None,
    "lip_sync_1_10": None,
    "final_video_watchability_1_10": None,
    "overall_score_1_10": None,
    "notes": "",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_report(report: dict) -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def fail_report(reason: str, *, manifest_items: list | None = None, provider_status: dict | None = None) -> None:
    report = {
        "sprint": 29,
        "status": "FAIL",
        "generated_at": now_iso(),
        "reason": reason,
        "manifest_path": str(MANIFEST_PATH),
        "provider_status": provider_status or CURRENT_PROVIDER_STATUS,
        "videos_required": VIDEOS_REQUIRED,
        "videos_found": len(manifest_items or []),
        "videos": [],
        "weakest_3_quality_problems": [
            "Evaluation input set is incomplete or not runnable.",
            "No human scoring can be trusted until all requested real videos complete with non-mock providers.",
            "Product quality ranking is blocked by missing completed FINAL_RENDER outputs.",
        ],
        "next_sprint_recommendation": "Complete Sprint 29 input manifest, then rerun this script without enabling mock providers.",
    }
    write_report(report)
    raise SystemExit(reason)


def load_manifest() -> list[dict]:
    if not MANIFEST_PATH.exists():
        fail_report("Manifest not found. Create storage/tmp/sprint29_inputs/manifest.json with at least 1 real video entry.")
    payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    items = payload.get("videos", payload if isinstance(payload, list) else [])
    if not isinstance(items, list):
        fail_report("Manifest must be a JSON array or an object with a videos array.")
    normalized = []
    for index, item in enumerate(items, start=1):
        path = pathlib.Path(item.get("path", ""))
        if not path.is_absolute():
            path = (MANIFEST_PATH.parent / path).resolve()
        normalized.append(
            {
                "index": index,
                "name": item.get("name") or f"Sprint 29 Video {index:02d}",
                "category": item.get("category") or "uncategorized",
                "source_language": item.get("source_language") or "auto",
                "target_language": item.get("target_language") or "tr",
                "path": str(path),
                "notes": item.get("notes") or "",
            }
        )
    if len(normalized) < VIDEOS_REQUIRED:
        fail_report("Manifest contains no videos.", manifest_items=normalized)
    missing = [item for item in normalized if not pathlib.Path(item["path"]).exists()]
    if missing:
        fail_report(
            "One or more manifest videos do not exist.",
            manifest_items=normalized,
        )
    return normalized


def login(session: requests.Session) -> dict:
    response = session.post(
        f"{BASE_URL}/auth/login",
        json={
            "email": os.getenv("SPRINT29_EMAIL", "editor@example.com"),
            "password": os.getenv("SPRINT29_PASSWORD", "editor123"),
        },
        timeout=30,
    )
    response.raise_for_status()
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def provider_status(session: requests.Session, headers: dict) -> dict:
    global CURRENT_PROVIDER_STATUS
    del headers
    response = session.get(f"{BASE_URL}/runtime/providers", timeout=30)
    response.raise_for_status()
    status = response.json()
    CURRENT_PROVIDER_STATUS = status
    providers = {item["capability"]: item["provider"] for item in status.get("providers", [])}
    problems = []
    if status.get("allow_mock_providers") is not False:
        problems.append("ALLOW_MOCK_PROVIDERS must be false.")
    if status.get("has_mock_provider"):
        problems.append("At least one mock provider is active.")
    for capability, expected in EXPECTED_PROVIDERS.items():
        actual = providers.get(capability)
        if actual != expected:
            problems.append(f"{capability} expected {expected}, got {actual}.")
    if problems:
        fail_report("Provider safety check failed: " + " ".join(problems), provider_status=status)
    return status


def wait_for_job(session: requests.Session, headers: dict, project_id: str, job_type: str, *, attempts: int, delay: int) -> dict:
    last_payload = None
    for _ in range(attempts):
        response = session.get(f"{BASE_URL}/projects/{project_id}", headers=headers, timeout=60)
        response.raise_for_status()
        payload = response.json()
        last_payload = payload
        jobs = [job for job in payload.get("jobs", []) if job["job_type"] == job_type]
        if jobs:
            latest = jobs[0]
            if latest["state"] == "COMPLETED":
                return payload
            if latest["state"] == "FAILED":
                raise RuntimeError(f"{job_type} failed: {json.dumps(latest.get('error_json'), ensure_ascii=False)}")
        time.sleep(delay)
    raise TimeoutError(f"Timed out waiting for {job_type}; last detail: {json.dumps(last_payload, ensure_ascii=False)[:2000]}")


def post_and_wait(session: requests.Session, headers: dict, project_id: str, endpoint: str, job_type: str, *, attempts: int = 1800) -> dict:
    response = session.post(f"{BASE_URL}/projects/{project_id}/{endpoint}", headers=headers, timeout=120)
    response.raise_for_status()
    return wait_for_job(session, headers, project_id, job_type, attempts=attempts, delay=2)


def latest_artifact(detail: dict, artifact_type: str) -> dict | None:
    artifacts = [artifact for artifact in detail.get("artifacts", []) if artifact["artifact_type"] == artifact_type]
    return artifacts[0] if artifacts else None


def audio_stream_count(artifact: dict | None) -> int | None:
    if not artifact:
        return None
    return len([stream for stream in artifact.get("metadata_json", {}).get("streams", []) if stream.get("codec_type") == "audio"])


def max_timeline_end(detail: dict) -> int | None:
    ends = [clip.get("end_ms") for clip in detail.get("timeline_clips", []) if clip.get("end_ms") is not None]
    return max(ends) if ends else None


def job_summary(detail: dict) -> list[dict]:
    return [
        {
            "job_type": job["job_type"],
            "state": job["state"],
            "worker_name": job.get("worker_name"),
            "error_json": job.get("error_json"),
            "output_json": job.get("output_json"),
            "created_at": job.get("created_at"),
            "updated_at": job.get("updated_at"),
        }
        for job in detail.get("jobs", [])
    ]


def create_project(session: requests.Session, headers: dict, item: dict) -> str:
    response = session.post(
        f"{BASE_URL}/projects",
        headers=headers,
        json={
            "name": f"Sprint 29 {item['index']:02d} {item['category']} - {item['name']}",
            "source_language": item["source_language"],
            "target_language": item["target_language"],
            "description": "Sprint 29 product evaluation real-provider run.",
        },
        timeout=60,
    )
    response.raise_for_status()
    return response.json()["id"]


def upload_video(session: requests.Session, headers: dict, project_id: str, path: pathlib.Path) -> dict:
    with path.open("rb") as handle:
        response = session.post(
            f"{BASE_URL}/projects/{project_id}/upload",
            headers=headers,
            files={"file": (path.name, handle, "video/mp4")},
            timeout=600,
        )
    response.raise_for_status()
    return response.json()


def prepare_voice_profiles(session: requests.Session, headers: dict, project_id: str, detail: dict) -> dict:
    response = session.post(f"{BASE_URL}/projects/{project_id}/characters/from-speakers", headers=headers, timeout=120)
    response.raise_for_status()
    detail = response.json()
    for character in detail.get("characters", []):
        response = session.post(
            f"{BASE_URL}/projects/{project_id}/characters/{character['id']}/voice-sample",
            headers=headers,
            timeout=120,
        )
        response.raise_for_status()
        detail = wait_for_job(session, headers, project_id, "VOICE_SAMPLE_EXTRACT", attempts=1200, delay=2)
        response = session.post(
            f"{BASE_URL}/projects/{project_id}/characters/{character['id']}/voice-profile/from-sample",
            headers=headers,
            timeout=120,
        )
        response.raise_for_status()
        detail = response.json()
    return detail


def collect_video_metrics(item: dict, project_id: str, detail: dict, elapsed_seconds: float) -> dict:
    source = latest_artifact(detail, "SOURCE_VIDEO")
    final_render = latest_artifact(detail, "FINAL_RENDER")
    final_audio = latest_artifact(detail, "FINAL_DUB_AUDIO")
    lipsync = latest_artifact(detail, "LIPSYNC_VIDEO")
    samples = [artifact for artifact in detail.get("artifacts", []) if artifact["artifact_type"] == "VOICE_SAMPLE_AUDIO"]
    references = [artifact for artifact in detail.get("artifacts", []) if artifact["artifact_type"] == "VOICE_REFERENCE_AUDIO"]
    dub_segments = detail.get("dub_segments", [])
    cosyvoice_metadata = [
        {
            "dub_segment_id": segment["id"],
            "provider": segment.get("provider"),
            "voice_id": segment.get("voice_id"),
            "duration_ms": segment.get("duration_ms"),
            "metadata_json": segment.get("metadata_json"),
        }
        for segment in dub_segments
    ]
    sample_metrics = [
        {
            "artifact_id": artifact["id"],
            "duration_ms": artifact.get("duration_ms"),
            "sample_quality_score": artifact.get("metadata_json", {}).get("sample_quality_score"),
            "reference_duration_ms": artifact.get("metadata_json", {}).get("reference_duration_ms"),
            "normalized": artifact.get("metadata_json", {}).get("normalized"),
            "silence_trimmed": artifact.get("metadata_json", {}).get("silence_trimmed"),
        }
        for artifact in samples + references
    ]
    jobs = job_summary(detail)
    errors = [job for job in jobs if job["state"] == "FAILED"]
    return {
        "input": item,
        "project_id": project_id,
        "status": "PASS" if final_render and not errors else "FAIL",
        "technical_metrics": {
            "asr_quality_score": detail.get("transcript_quality_score"),
            "transcript_segment_count": len(detail.get("transcript_segments", [])),
            "translation_segment_count": len(detail.get("translation_segments", [])),
            "timeline_max_end_ms": max_timeline_end(detail),
            "source_video_duration_ms": source.get("duration_ms") if source else None,
            "final_render_duration_ms": final_render.get("duration_ms") if final_render else None,
            "final_dub_audio_duration_ms": final_audio.get("duration_ms") if final_audio else None,
            "voice_sample_metrics": sample_metrics,
            "cosyvoice_provider_metadata": cosyvoice_metadata,
            "musetalk": {
                "artifact_id": lipsync.get("id") if lipsync else None,
                "duration_ms": lipsync.get("duration_ms") if lipsync else None,
                "provider": lipsync.get("metadata_json", {}).get("provider") if lipsync else None,
                "mock": lipsync.get("metadata_json", {}).get("mock") if lipsync else None,
                "quality_preset": lipsync.get("metadata_json", {}).get("quality_preset") if lipsync else None,
                "fps": lipsync.get("metadata_json", {}).get("fps") if lipsync else None,
                "resolution": lipsync.get("metadata_json", {}).get("resolution") if lipsync else None,
                "processing_time_ms": lipsync.get("metadata_json", {}).get("processing_time_ms") if lipsync else None,
            },
            "final_render": {
                "artifact_id": final_render.get("id") if final_render else None,
                "storage_path": final_render.get("storage_path") if final_render else None,
                "size_bytes": final_render.get("size_bytes") if final_render else None,
                "audio_stream_count": audio_stream_count(final_render),
                "source_video_artifact_id": final_render.get("metadata_json", {}).get("source_video_artifact_id") if final_render else None,
                "source_video_artifact_type": final_render.get("metadata_json", {}).get("source_video_artifact_type") if final_render else None,
            },
            "processing_time_seconds": round(elapsed_seconds, 3),
            "job_errors": [job["error_json"] for job in errors],
        },
        "jobs": jobs,
        "human_evaluation": dict(HUMAN_EVALUATION_TEMPLATE),
    }


def weakest_quality_problems(video_reports: list[dict]) -> list[str]:
    problems = []
    for report in video_reports:
        metrics = report.get("technical_metrics", {})
        name = report["input"]["name"]
        source_ms = metrics.get("source_video_duration_ms") or 0
        render_ms = metrics.get("final_render_duration_ms") or 0
        if source_ms and render_ms and abs(source_ms - render_ms) > 500:
            problems.append(f"{name}: final render duration differs from source by {abs(source_ms - render_ms)} ms.")
        if (metrics.get("asr_quality_score") or 0) < 0.7:
            problems.append(f"{name}: ASR quality score is below 0.70.")
        if not metrics.get("voice_sample_metrics"):
            problems.append(f"{name}: no voice sample/reference metrics were produced.")
        if metrics.get("final_render", {}).get("audio_stream_count") != 1:
            problems.append(f"{name}: final render audio stream count is not 1.")
        if metrics.get("musetalk", {}).get("mock") is not False:
            problems.append(f"{name}: MuseTalk metadata does not confirm mock=false.")
        if report.get("status") != "PASS":
            problems.append(f"{name}: pipeline did not reach PASS.")
    return (problems + ["Human scoring is still empty; watchability needs manual review."])[:3]


def main() -> None:
    session = requests.Session()
    headers = login(session)
    status = provider_status(session, headers)
    manifest = load_manifest()
    reports = []
    started_all = time.perf_counter()
    for item in manifest:
        video_started = time.perf_counter()
        detail = None
        project_id = None
        try:
            project_id = create_project(session, headers, item)
            upload_video(session, headers, project_id, pathlib.Path(item["path"]))
            detail = wait_for_job(session, headers, project_id, "DIARIZE", attempts=1800, delay=2)
            detail = prepare_voice_profiles(session, headers, project_id, detail)
            detail = post_and_wait(session, headers, project_id, "tts", "TTS", attempts=2400)
            detail = post_and_wait(session, headers, project_id, "audio-mix", "AUDIO_MIX", attempts=1200)
            detail = post_and_wait(session, headers, project_id, "lip-sync", "LIP_SYNC", attempts=2400)
            detail = post_and_wait(session, headers, project_id, "render", "RENDER", attempts=1200)
            reports.append(collect_video_metrics(item, project_id, detail, time.perf_counter() - video_started))
        except Exception as exc:
            if project_id:
                try:
                    response = session.get(f"{BASE_URL}/projects/{project_id}", headers=headers, timeout=60)
                    detail = response.json() if response.ok else {"jobs": [], "artifacts": []}
                except Exception:
                    detail = {"jobs": [], "artifacts": []}
            reports.append(
                {
                    "input": item,
                    "project_id": project_id,
                    "status": "FAIL",
                    "technical_metrics": {
                        "processing_time_seconds": round(time.perf_counter() - video_started, 3),
                        "job_errors": [str(exc)],
                    },
                    "jobs": job_summary(detail or {}),
                    "human_evaluation": dict(HUMAN_EVALUATION_TEMPLATE),
                }
            )
            break
        finally:
            write_report(
                {
                    "sprint": 29,
                    "status": "RUNNING",
                    "generated_at": now_iso(),
                    "provider_status": status,
                    "videos_required": len(manifest),
                    "videos_completed": len([item for item in reports if item["status"] == "PASS"]),
                    "videos": reports,
                }
            )
    pass_count = len([item for item in reports if item["status"] == "PASS"])
    final_status = "PASS" if pass_count >= len(manifest) and len(reports) >= len(manifest) else "FAIL"
    report = {
        "sprint": 29,
        "status": final_status,
        "generated_at": now_iso(),
        "provider_status": status,
        "videos_required": len(manifest),
        "videos_processed": len(reports),
        "videos_passed": pass_count,
        "total_processing_time_seconds": round(time.perf_counter() - started_all, 3),
        "videos": reports,
        "weakest_3_quality_problems": weakest_quality_problems(reports),
        "next_sprint_recommendation": (
            "Prioritize the weakest manually scored dimension after reviewing the 10 FINAL_RENDER files; "
            "start with ASR/translation if transcript_quality_score is low, otherwise tune voice sample selection and MuseTalk crop quality."
        ),
    }
    write_report(report)
    if final_status != "PASS":
        raise SystemExit("Sprint 29 product evaluation did not complete all requested real videos.")
    print(json.dumps({"status": final_status, "output": str(OUTPUT_PATH), "videos_passed": pass_count}, ensure_ascii=False))


if __name__ == "__main__":
    main()
'@ | docker compose exec -T api sh -lc "cd /workspace/apps/api && SPRINT29_MANIFEST_PATH='$containerManifestPath' SPRINT29_OUTPUT_PATH='$containerOutputPath' python -"
if ($LASTEXITCODE -ne 0) {
  throw "Sprint 29 product evaluation failed with exit code $LASTEXITCODE. Report: $outputPath"
}
