from pathlib import Path

from psycopg.rows import dict_row

from tests.integration.test_sprint11_acceptance import wait_for_audio_mix_ready
from tests.integration.test_sprint10_acceptance import wait_for_tts_ready
from tests.integration.test_sprint7_acceptance import create_project, upload_video, wait_for_pipeline_ready


RENDER_EVENTS = {
    "RENDER_STARTED",
    "RENDER_COMPLETED",
}


def wait_for_render_ready(client, auth_headers, project_id: str, attempts: int = 60, delay_seconds: float = 2.0):
    import time

    detail = None
    for _ in range(attempts):
        detail = client.get(f"/projects/{project_id}", headers=auth_headers)
        assert detail.status_code == 200, detail.text
        payload = detail.json()
        jobs_by_type = {job["job_type"]: job for job in payload["jobs"]}
        final_artifacts = [artifact for artifact in payload["artifacts"] if artifact["artifact_type"] == "FINAL_RENDER"]
        if "RENDER" in jobs_by_type and jobs_by_type["RENDER"]["state"] == "COMPLETED" and final_artifacts:
            return payload
        time.sleep(delay_seconds)
    raise AssertionError(f"Render pipeline did not complete for project {project_id}")


def test_sprint12_render_acceptance(client, auth_headers, db_conn, storage_root, valid_sample_video_file: Path):
    project = create_project(client, auth_headers, name="Sprint 12 Acceptance Project")
    project_id = project["id"]
    upload_video(client, auth_headers, project_id, valid_sample_video_file)
    wait_for_pipeline_ready(client, auth_headers, project_id)

    tts_response = client.post(f"/projects/{project_id}/tts", headers=auth_headers)
    assert tts_response.status_code == 200, tts_response.text
    wait_for_tts_ready(client, auth_headers, project_id)

    mix_response = client.post(f"/projects/{project_id}/audio-mix", headers=auth_headers)
    assert mix_response.status_code == 200, mix_response.text
    wait_for_audio_mix_ready(client, auth_headers, project_id)

    render_response = client.post(f"/projects/{project_id}/render", headers=auth_headers)
    assert render_response.status_code == 200, render_response.text
    detail = wait_for_render_ready(client, auth_headers, project_id)

    jobs = {job["job_type"]: job for job in detail["jobs"]}
    assert jobs["RENDER"]["state"] == "COMPLETED"
    assert jobs["RENDER"]["output_json"]["final_render_artifact_id"]

    final_renders = [artifact for artifact in detail["artifacts"] if artifact["artifact_type"] == "FINAL_RENDER"]
    assert len(final_renders) == 1
    final_render = final_renders[0]
    render_path = storage_root / final_render["storage_path"]
    assert render_path.exists()
    assert render_path.stat().st_size > 0
    assert final_render["parent_artifact_ids"]

    event_types = {event["event_type"] for event in detail["events"]}
    for event_type in RENDER_EVENTS:
        assert event_type in event_types

    with db_conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            select width, height, audio_channels, sample_rate, metadata_json
            from artifacts
            where id = %s
            """,
            (final_render["id"],),
        )
        row = cur.fetchone()
        assert row["width"] == 1920
        assert row["height"] == 1080
        assert row["audio_channels"] == 1
        assert row["sample_rate"] is not None
        streams = row["metadata_json"]["streams"]
        audio_streams = [stream for stream in streams if stream.get("codec_type") == "audio"]
        assert len(audio_streams) == 1


def test_sprint12_failed_render_job_does_not_break_api(client, auth_headers, db_conn, valid_sample_video_file: Path):
    project = create_project(client, auth_headers, name="Sprint 12 Failed Render")
    project_id = project["id"]
    upload_video(client, auth_headers, project_id, valid_sample_video_file)
    wait_for_pipeline_ready(client, auth_headers, project_id)

    tts_response = client.post(f"/projects/{project_id}/tts", headers=auth_headers)
    assert tts_response.status_code == 200, tts_response.text
    wait_for_tts_ready(client, auth_headers, project_id)

    mix_response = client.post(f"/projects/{project_id}/audio-mix", headers=auth_headers)
    assert mix_response.status_code == 200, mix_response.text
    detail = wait_for_audio_mix_ready(client, auth_headers, project_id)
    final_dub_audio = next(artifact for artifact in detail["artifacts"] if artifact["artifact_type"] == "FINAL_DUB_AUDIO")

    with db_conn.cursor() as cur:
        cur.execute("delete from artifacts where id = %s", (final_dub_audio["id"],))
        db_conn.commit()

    render_response = client.post(f"/projects/{project_id}/render", headers=auth_headers)
    assert render_response.status_code == 200, render_response.text

    import time

    failed_detail = None
    for _ in range(30):
        response = client.get(f"/projects/{project_id}", headers=auth_headers)
        assert response.status_code == 200, response.text
        failed_detail = response.json()
        jobs = {job["job_type"]: job for job in failed_detail["jobs"]}
        if "RENDER" in jobs and jobs["RENDER"]["state"] == "FAILED":
            break
        time.sleep(2)

    assert failed_detail is not None
    failed_jobs = {job["job_type"]: job for job in failed_detail["jobs"]}
    assert failed_jobs["RENDER"]["state"] == "FAILED"
    assert "artifacts" in failed_detail

    with db_conn.cursor(row_factory=dict_row) as cur:
        cur.execute("select error_json from jobs where id = %s", (failed_jobs["RENDER"]["id"],))
        row = cur.fetchone()
        assert row["error_json"]

        cur.execute("select event_type from project_events where project_id = %s", (project_id,))
        event_types = {item["event_type"] for item in cur.fetchall()}
        assert "JOB_FAILED" in event_types
