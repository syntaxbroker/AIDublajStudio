from pathlib import Path

from psycopg.rows import dict_row

from tests.integration.test_sprint10_acceptance import wait_for_tts_ready
from tests.integration.test_sprint7_acceptance import create_project, upload_video, wait_for_pipeline_ready


AUDIO_MIX_EVENTS = {
    "AUDIO_MIX_STARTED",
    "AUDIO_SEGMENT_PLACED",
    "AUDIO_MIX_COMPLETED",
}


def wait_for_audio_mix_ready(client, auth_headers, project_id: str, attempts: int = 60, delay_seconds: float = 2.0):
    import time

    detail = None
    for _ in range(attempts):
        detail = client.get(f"/projects/{project_id}", headers=auth_headers)
        assert detail.status_code == 200, detail.text
        payload = detail.json()
        jobs_by_type = {job["job_type"]: job for job in payload["jobs"]}
        final_artifacts = [artifact for artifact in payload["artifacts"] if artifact["artifact_type"] == "FINAL_DUB_AUDIO"]
        if "AUDIO_MIX" in jobs_by_type and jobs_by_type["AUDIO_MIX"]["state"] == "COMPLETED" and final_artifacts:
            return payload
        time.sleep(delay_seconds)
    raise AssertionError(f"Audio mix pipeline did not complete for project {project_id}")


def test_sprint11_audio_mix_acceptance(client, auth_headers, db_conn, storage_root, valid_sample_video_file: Path):
    project = create_project(client, auth_headers, name="Sprint 11 Acceptance Project")
    project_id = project["id"]
    upload_video(client, auth_headers, project_id, valid_sample_video_file)
    wait_for_pipeline_ready(client, auth_headers, project_id)

    tts_response = client.post(f"/projects/{project_id}/tts", headers=auth_headers)
    assert tts_response.status_code == 200, tts_response.text
    wait_for_tts_ready(client, auth_headers, project_id)

    mix_response = client.post(f"/projects/{project_id}/audio-mix", headers=auth_headers)
    assert mix_response.status_code == 200, mix_response.text
    detail = wait_for_audio_mix_ready(client, auth_headers, project_id)

    jobs = {job["job_type"]: job for job in detail["jobs"]}
    assert jobs["AUDIO_MIX"]["state"] == "COMPLETED"
    assert jobs["AUDIO_MIX"]["output_json"]["final_audio_artifact_id"]

    final_artifacts = [artifact for artifact in detail["artifacts"] if artifact["artifact_type"] == "FINAL_DUB_AUDIO"]
    assert len(final_artifacts) == 1
    final_artifact = final_artifacts[0]
    artifact_path = storage_root / final_artifact["storage_path"]
    assert artifact_path.exists()
    assert artifact_path.stat().st_size > 0
    assert final_artifact["parent_artifact_ids"]

    event_types = {event["event_type"] for event in detail["events"]}
    for event_type in AUDIO_MIX_EVENTS:
        assert event_type in event_types

    with db_conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            select max(end_ms) as timeline_end_ms
            from timeline_clips
            where project_id = %s
            """,
            (project_id,),
        )
        timeline_end_ms = int(cur.fetchone()["timeline_end_ms"])

        cur.execute(
            """
            select max(duration_ms) as video_duration_ms
            from artifacts
            where project_id = %s
            and artifact_type in ('SOURCE_VIDEO', 'PROXY_VIDEO')
            and duration_ms is not null
            """,
            (project_id,),
        )
        video_duration_ms = int(cur.fetchone()["video_duration_ms"])

        cur.execute(
            """
            select duration_ms, storage_path, audio_channels, sample_rate
            from artifacts
            where id = %s
            """,
            (final_artifact["id"],),
        )
        row = cur.fetchone()
        assert row["duration_ms"] is not None
        assert int(row["duration_ms"]) >= timeline_end_ms
        assert abs(int(row["duration_ms"]) - video_duration_ms) <= 100
        assert row["audio_channels"] == 1
        assert row["sample_rate"] == 22050
        assert (storage_root / row["storage_path"]).exists()


def test_sprint11_failed_audio_mix_job_does_not_break_api(client, auth_headers, db_conn, valid_sample_video_file: Path):
    project = create_project(client, auth_headers, name="Sprint 11 Failed Audio Mix")
    project_id = project["id"]
    upload_video(client, auth_headers, project_id, valid_sample_video_file)
    wait_for_pipeline_ready(client, auth_headers, project_id)

    tts_response = client.post(f"/projects/{project_id}/tts", headers=auth_headers)
    assert tts_response.status_code == 200, tts_response.text
    detail = wait_for_tts_ready(client, auth_headers, project_id)
    first_dub_segment = detail["dub_segments"][0]

    with db_conn.cursor() as cur:
        cur.execute("delete from artifacts where id = %s", (first_dub_segment["audio_artifact_id"],))
        db_conn.commit()

    mix_response = client.post(f"/projects/{project_id}/audio-mix", headers=auth_headers)
    assert mix_response.status_code == 200, mix_response.text

    import time

    failed_detail = None
    for _ in range(30):
        response = client.get(f"/projects/{project_id}", headers=auth_headers)
        assert response.status_code == 200, response.text
        failed_detail = response.json()
        jobs = {job["job_type"]: job for job in failed_detail["jobs"]}
        if "AUDIO_MIX" in jobs and jobs["AUDIO_MIX"]["state"] == "FAILED":
            break
        time.sleep(2)

    assert failed_detail is not None
    failed_jobs = {job["job_type"]: job for job in failed_detail["jobs"]}
    assert failed_jobs["AUDIO_MIX"]["state"] == "FAILED"
    assert "artifacts" in failed_detail
    assert "dub_segments" in failed_detail

    with db_conn.cursor(row_factory=dict_row) as cur:
        cur.execute("select error_json from jobs where id = %s", (failed_jobs["AUDIO_MIX"]["id"],))
        row = cur.fetchone()
        assert row["error_json"]

        cur.execute("select event_type from project_events where project_id = %s", (project_id,))
        event_types = {item["event_type"] for item in cur.fetchall()}
        assert "JOB_FAILED" in event_types
