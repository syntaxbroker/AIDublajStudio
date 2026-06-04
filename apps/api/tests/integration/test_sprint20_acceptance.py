from pathlib import Path

from psycopg.rows import dict_row

from tests.integration.test_sprint10_acceptance import wait_for_tts_ready
from tests.integration.test_sprint11_acceptance import wait_for_audio_mix_ready
from tests.integration.test_sprint7_acceptance import create_project, upload_video, wait_for_pipeline_ready


LIP_SYNC_EVENTS = {
    "LIP_SYNC_STARTED",
    "LIP_SYNC_COMPLETED",
}


def wait_for_lip_sync_ready(client, auth_headers, project_id: str, attempts: int = 60, delay_seconds: float = 2.0):
    import time

    detail = None
    for _ in range(attempts):
        detail = client.get(f"/projects/{project_id}", headers=auth_headers)
        assert detail.status_code == 200, detail.text
        payload = detail.json()
        jobs_by_type = {job["job_type"]: job for job in payload["jobs"]}
        artifacts = [artifact for artifact in payload["artifacts"] if artifact["artifact_type"] == "LIPSYNC_VIDEO"]
        if "LIP_SYNC" in jobs_by_type and jobs_by_type["LIP_SYNC"]["state"] == "COMPLETED" and artifacts:
            return payload
        time.sleep(delay_seconds)
    raise AssertionError(f"Lip sync pipeline did not complete for project {project_id}")


def wait_for_lip_sync_failed(client, auth_headers, project_id: str, attempts: int = 30, delay_seconds: float = 2.0):
    import time

    detail = None
    for _ in range(attempts):
        detail = client.get(f"/projects/{project_id}", headers=auth_headers)
        assert detail.status_code == 200, detail.text
        payload = detail.json()
        jobs_by_type = {job["job_type"]: job for job in payload["jobs"]}
        if "LIP_SYNC" in jobs_by_type and jobs_by_type["LIP_SYNC"]["state"] == "FAILED":
            return payload
        time.sleep(delay_seconds)
    raise AssertionError(f"Lip sync failure did not surface for project {project_id}")


def prepare_project_with_final_audio(client, auth_headers, valid_sample_video_file: Path):
    project = create_project(client, auth_headers, name="Sprint 20 Lip Sync Acceptance")
    project_id = project["id"]
    upload_video(client, auth_headers, project_id, valid_sample_video_file)
    wait_for_pipeline_ready(client, auth_headers, project_id)

    tts_response = client.post(f"/projects/{project_id}/tts", headers=auth_headers)
    assert tts_response.status_code == 200, tts_response.text
    wait_for_tts_ready(client, auth_headers, project_id)

    mix_response = client.post(f"/projects/{project_id}/audio-mix", headers=auth_headers)
    assert mix_response.status_code == 200, mix_response.text
    wait_for_audio_mix_ready(client, auth_headers, project_id)
    return project_id


def test_sprint20_lip_sync_acceptance(client, auth_headers, db_conn, storage_root, valid_sample_video_file: Path):
    project_id = prepare_project_with_final_audio(client, auth_headers, valid_sample_video_file)

    lip_sync_response = client.post(f"/projects/{project_id}/lip-sync", headers=auth_headers)
    assert lip_sync_response.status_code == 200, lip_sync_response.text
    detail = wait_for_lip_sync_ready(client, auth_headers, project_id)

    jobs = {job["job_type"]: job for job in detail["jobs"]}
    assert jobs["LIP_SYNC"]["state"] == "COMPLETED"
    assert jobs["LIP_SYNC"]["output_json"]["lipsync_video_artifact_id"]

    lipsync_artifacts = [artifact for artifact in detail["artifacts"] if artifact["artifact_type"] == "LIPSYNC_VIDEO"]
    assert len(lipsync_artifacts) == 1
    lipsync_artifact = lipsync_artifacts[0]
    lipsync_path = storage_root / lipsync_artifact["storage_path"]
    assert lipsync_path.exists()
    assert lipsync_path.stat().st_size > 0
    assert lipsync_artifact["parent_artifact_ids"]

    event_types = {event["event_type"] for event in detail["events"]}
    for event_type in LIP_SYNC_EVENTS:
        assert event_type in event_types

    second_response = client.post(f"/projects/{project_id}/lip-sync", headers=auth_headers)
    assert second_response.status_code == 200, second_response.text
    second_detail = second_response.json()
    completed_lip_sync_jobs = [
        job for job in second_detail["jobs"] if job["job_type"] == "LIP_SYNC" and job["state"] == "COMPLETED"
    ]
    assert len(completed_lip_sync_jobs) == 1
    assert len([artifact for artifact in second_detail["artifacts"] if artifact["artifact_type"] == "LIPSYNC_VIDEO"]) == 1

    with db_conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            select artifact_type, storage_path, metadata_json
            from artifacts
            where id = %s
            """,
            (lipsync_artifact["id"],),
        )
        row = cur.fetchone()
        assert row["artifact_type"] == "LIPSYNC_VIDEO"
        assert (storage_root / row["storage_path"]).exists()
        assert row["metadata_json"]["provider"] == "mock"


def test_sprint20_missing_final_dub_audio_fails_lip_sync(client, auth_headers, db_conn, valid_sample_video_file: Path):
    project = create_project(client, auth_headers, name="Sprint 20 Missing Final Dub Audio")
    project_id = project["id"]
    upload_video(client, auth_headers, project_id, valid_sample_video_file)
    wait_for_pipeline_ready(client, auth_headers, project_id)

    lip_sync_response = client.post(f"/projects/{project_id}/lip-sync", headers=auth_headers)
    assert lip_sync_response.status_code == 200, lip_sync_response.text
    detail = wait_for_lip_sync_failed(client, auth_headers, project_id)

    jobs = {job["job_type"]: job for job in detail["jobs"]}
    assert jobs["LIP_SYNC"]["state"] == "FAILED"
    assert "artifacts" in detail

    health_response = client.get("/health")
    assert health_response.status_code == 200, health_response.text

    with db_conn.cursor(row_factory=dict_row) as cur:
        cur.execute("select error_json from jobs where id = %s", (jobs["LIP_SYNC"]["id"],))
        row = cur.fetchone()
        assert row["error_json"]

        cur.execute("select event_type from project_events where project_id = %s", (project_id,))
        event_types = {item["event_type"] for item in cur.fetchall()}
        assert "JOB_FAILED" in event_types
