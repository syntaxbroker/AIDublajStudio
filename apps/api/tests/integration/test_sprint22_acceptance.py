from pathlib import Path

from psycopg.rows import dict_row

from tests.integration.test_sprint12_acceptance import wait_for_render_ready
from tests.integration.test_sprint20_acceptance import prepare_project_with_final_audio, wait_for_lip_sync_ready
from tests.integration.test_sprint7_acceptance import create_project, upload_video, wait_for_pipeline_ready
from tests.integration.test_sprint10_acceptance import wait_for_tts_ready
from tests.integration.test_sprint11_acceptance import wait_for_audio_mix_ready


def _render_project(client, auth_headers, project_id: str):
    response = client.post(f"/projects/{project_id}/render", headers=auth_headers)
    assert response.status_code == 200, response.text
    return wait_for_render_ready(client, auth_headers, project_id)


def _audio_streams(metadata_json: dict) -> list[dict]:
    return [stream for stream in metadata_json.get("streams", []) if stream.get("codec_type") == "audio"]


def test_sprint22_render_uses_lipsync_video_when_available(
    client,
    auth_headers,
    db_conn,
    storage_root,
    valid_sample_video_file: Path,
):
    project_id = prepare_project_with_final_audio(client, auth_headers, valid_sample_video_file)

    lip_sync_response = client.post(f"/projects/{project_id}/lip-sync", headers=auth_headers)
    assert lip_sync_response.status_code == 200, lip_sync_response.text
    detail = wait_for_lip_sync_ready(client, auth_headers, project_id)
    lipsync_video = next(artifact for artifact in detail["artifacts"] if artifact["artifact_type"] == "LIPSYNC_VIDEO")

    detail = _render_project(client, auth_headers, project_id)
    final_render = next(artifact for artifact in detail["artifacts"] if artifact["artifact_type"] == "FINAL_RENDER")
    final_render_path = storage_root / final_render["storage_path"]
    assert final_render_path.exists()
    assert lipsync_video["id"] in final_render["parent_artifact_ids"]
    assert final_render["metadata_json"]["source_video_artifact_id"] == lipsync_video["id"]
    assert final_render["metadata_json"]["source_video_artifact_type"] == "LIPSYNC_VIDEO"
    assert final_render["metadata_json"]["source_video_label"] == "Lip Sync Video"
    assert len(_audio_streams(final_render["metadata_json"])) == 1

    jobs = {job["job_type"]: job for job in detail["jobs"]}
    assert jobs["RENDER"]["output_json"]["video_source_artifact_id"] == lipsync_video["id"]
    assert jobs["RENDER"]["output_json"]["video_source_artifact_type"] == "LIPSYNC_VIDEO"


def test_sprint22_render_falls_back_to_source_video_without_lipsync(
    client,
    auth_headers,
    valid_sample_video_file: Path,
):
    project = create_project(client, auth_headers, name="Sprint 22 Source Fallback")
    project_id = project["id"]
    upload_video(client, auth_headers, project_id, valid_sample_video_file)
    wait_for_pipeline_ready(client, auth_headers, project_id)

    tts_response = client.post(f"/projects/{project_id}/tts", headers=auth_headers)
    assert tts_response.status_code == 200, tts_response.text
    wait_for_tts_ready(client, auth_headers, project_id)

    mix_response = client.post(f"/projects/{project_id}/audio-mix", headers=auth_headers)
    assert mix_response.status_code == 200, mix_response.text
    detail = wait_for_audio_mix_ready(client, auth_headers, project_id)
    source_video = next(artifact for artifact in detail["artifacts"] if artifact["artifact_type"] == "SOURCE_VIDEO")

    detail = _render_project(client, auth_headers, project_id)
    final_render = next(artifact for artifact in detail["artifacts"] if artifact["artifact_type"] == "FINAL_RENDER")
    assert source_video["id"] in final_render["parent_artifact_ids"]
    assert final_render["metadata_json"]["source_video_artifact_id"] == source_video["id"]
    assert final_render["metadata_json"]["source_video_artifact_type"] == "SOURCE_VIDEO"
    assert final_render["metadata_json"]["source_video_label"] == "Source Video"
    assert len(_audio_streams(final_render["metadata_json"])) == 1


def test_sprint22_missing_selected_lipsync_file_fails_render_and_api_stays_up(
    client,
    auth_headers,
    db_conn,
    valid_sample_video_file: Path,
):
    project_id = prepare_project_with_final_audio(client, auth_headers, valid_sample_video_file)

    lip_sync_response = client.post(f"/projects/{project_id}/lip-sync", headers=auth_headers)
    assert lip_sync_response.status_code == 200, lip_sync_response.text
    detail = wait_for_lip_sync_ready(client, auth_headers, project_id)
    lipsync_video = next(artifact for artifact in detail["artifacts"] if artifact["artifact_type"] == "LIPSYNC_VIDEO")

    with db_conn.cursor(row_factory=dict_row) as cur:
        cur.execute("update artifacts set storage_path = %s where id = %s", ("missing/lipsync.mp4", lipsync_video["id"]))
        db_conn.commit()

    response = client.post(f"/projects/{project_id}/render", headers=auth_headers)
    assert response.status_code == 200, response.text

    import time

    failed_detail = None
    for _ in range(30):
        detail_response = client.get(f"/projects/{project_id}", headers=auth_headers)
        assert detail_response.status_code == 200, detail_response.text
        failed_detail = detail_response.json()
        jobs = {job["job_type"]: job for job in failed_detail["jobs"]}
        if "RENDER" in jobs and jobs["RENDER"]["state"] == "FAILED":
            break
        time.sleep(2)

    assert failed_detail is not None
    jobs = {job["job_type"]: job for job in failed_detail["jobs"]}
    assert jobs["RENDER"]["state"] == "FAILED"
    assert jobs["RENDER"]["error_json"]

    health_response = client.get("/health")
    assert health_response.status_code == 200, health_response.text

