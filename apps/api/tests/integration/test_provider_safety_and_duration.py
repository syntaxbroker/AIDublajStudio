from pathlib import Path

import pytest

from tests.integration.test_sprint10_acceptance import wait_for_tts_ready
from tests.integration.test_sprint11_acceptance import wait_for_audio_mix_ready
from tests.integration.test_sprint12_acceptance import wait_for_render_ready
from tests.integration.test_sprint7_acceptance import create_project, upload_video, wait_for_pipeline_ready


def _thirty_second_sample() -> Path:
    sample = Path("/workspace/storage/tmp/sprint23_videos/qa11_sr_artillery_medium.mp4")
    if not sample.exists():
        pytest.skip(f"30s QA sample video is not available at {sample}")
    return sample


def test_provider_status_reports_mock_warning(client):
    response = client.get("/runtime/providers")
    assert response.status_code == 200, response.text
    payload = response.json()
    providers = {item["capability"]: item for item in payload["providers"]}
    assert providers["ASR_PROVIDER"]["provider"] == "mock"
    assert providers["ASR_PROVIDER"]["is_mock"] is True
    assert payload["has_mock_provider"] is True
    assert "beep-tone audio" in payload["warning"]


def test_ui_processing_is_blocked_when_mock_provider_is_active(client, auth_headers, valid_sample_video_file: Path):
    project = create_project(client, auth_headers, name="Provider Safety Block")
    with valid_sample_video_file.open("rb") as handle:
        response = client.post(
            f"/projects/{project['id']}/upload",
            headers={**auth_headers, "X-AIDublaj-Client": "web"},
            files={"file": (valid_sample_video_file.name, handle, "video/mp4")},
        )
    assert response.status_code == 409, response.text
    payload = response.json()
    assert payload["error"]["code"] == "MOCK_PROVIDERS_BLOCKED"


def test_render_preserves_source_duration_when_mock_timeline_is_short(
    client,
    auth_headers,
    storage_root,
):
    sample = _thirty_second_sample()
    source_duration_ms = 30000

    project = create_project(client, auth_headers, name="Duration Padding Regression")
    project_id = project["id"]
    upload_video(client, auth_headers, project_id, sample)
    wait_for_pipeline_ready(client, auth_headers, project_id)

    tts_response = client.post(f"/projects/{project_id}/tts", headers=auth_headers)
    assert tts_response.status_code == 200, tts_response.text
    wait_for_tts_ready(client, auth_headers, project_id)

    mix_response = client.post(f"/projects/{project_id}/audio-mix", headers=auth_headers)
    assert mix_response.status_code == 200, mix_response.text
    mix_detail = wait_for_audio_mix_ready(client, auth_headers, project_id)
    final_audio = next(artifact for artifact in mix_detail["artifacts"] if artifact["artifact_type"] == "FINAL_DUB_AUDIO")
    assert abs((final_audio["duration_ms"] or 0) - source_duration_ms) <= 150

    render_response = client.post(f"/projects/{project_id}/render", headers=auth_headers)
    assert render_response.status_code == 200, render_response.text
    render_detail = wait_for_render_ready(client, auth_headers, project_id)
    final_render = next(artifact for artifact in render_detail["artifacts"] if artifact["artifact_type"] == "FINAL_RENDER")
    assert (storage_root / final_render["storage_path"]).exists()
    assert abs((final_render["duration_ms"] or 0) - source_duration_ms) <= 150

    diagnostics_response = client.get(f"/projects/{project_id}/diagnostics/durations", headers=auth_headers)
    assert diagnostics_response.status_code == 200, diagnostics_response.text
    diagnostics = diagnostics_response.json()
    assert diagnostics["max_timeline_end_ms"] == 3200
    durations = {item["artifact_type"]: item["duration_ms"] for item in diagnostics["artifacts"]}
    assert abs(durations["FINAL_DUB_AUDIO"] - source_duration_ms) <= 150
    assert abs(durations["FINAL_RENDER"] - source_duration_ms) <= 150
