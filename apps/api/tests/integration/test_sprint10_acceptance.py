from pathlib import Path

from psycopg.rows import dict_row

from tests.integration.test_sprint7_acceptance import create_project, upload_video, wait_for_pipeline_ready


TTS_EVENTS = {
    "TTS_STARTED",
    "DUB_SEGMENT_CREATED",
    "TTS_AUDIO_GENERATED",
    "TTS_COMPLETED",
}


def wait_for_tts_ready(client, auth_headers, project_id: str, attempts: int = 60, delay_seconds: float = 2.0):
    import time

    detail = None
    for _ in range(attempts):
        detail = client.get(f"/projects/{project_id}", headers=auth_headers)
        assert detail.status_code == 200, detail.text
        payload = detail.json()
        jobs_by_type = {job["job_type"]: job for job in payload["jobs"]}
        if "TTS" in jobs_by_type and jobs_by_type["TTS"]["state"] == "COMPLETED" and payload["dub_segments"]:
            return payload
        time.sleep(delay_seconds)
    raise AssertionError(f"TTS pipeline did not complete for project {project_id}")


def test_sprint10_tts_layer_acceptance(client, auth_headers, db_conn, storage_root, valid_sample_video_file: Path):
    project = create_project(client, auth_headers, name="Sprint 10 Acceptance Project")
    project_id = project["id"]
    upload_video(client, auth_headers, project_id, valid_sample_video_file)
    wait_for_pipeline_ready(client, auth_headers, project_id)

    characters_response = client.post(f"/projects/{project_id}/characters/from-speakers", headers=auth_headers)
    assert characters_response.status_code == 200, characters_response.text
    detail = characters_response.json()
    characters = detail["characters"]
    clips = detail["timeline_clips"]
    assert characters
    assert clips

    first_clip = clips[0]
    update_response = client.patch(
        f"/projects/{project_id}/timeline/clips/{first_clip['id']}",
        headers=auth_headers,
        json={
            "translation_text": "Merhaba John.",
            "character_id": characters[0]["id"],
        },
    )
    assert update_response.status_code == 200, update_response.text

    tts_response = client.post(f"/projects/{project_id}/tts", headers=auth_headers)
    assert tts_response.status_code == 200, tts_response.text

    detail = wait_for_tts_ready(client, auth_headers, project_id)
    jobs = {job["job_type"]: job for job in detail["jobs"]}
    assert jobs["TTS"]["state"] == "COMPLETED"
    assert jobs["TTS"]["output_json"]["dub_segment_count"] >= 1
    assert jobs["TTS"]["output_json"]["provider"] == "mock"

    dub_segments = detail["dub_segments"]
    artifacts = detail["artifacts"]
    timeline_clips = detail["timeline_clips"]
    tts_artifacts = [artifact for artifact in artifacts if artifact["artifact_type"] == "TTS_AUDIO"]

    assert dub_segments
    assert tts_artifacts
    assert all(segment["audio_artifact_id"] for segment in dub_segments)
    assert all(clip["dub_segment_id"] for clip in timeline_clips if (clip.get("translation_text") or clip.get("text")))

    first_dub_segment = next(item for item in dub_segments if item["timeline_clip_id"] == first_clip["id"])
    assert first_dub_segment["text"] == "Merhaba John."
    assert first_dub_segment["provider"] == "mock"
    assert first_dub_segment["duration_ms"] is not None

    linked_artifact = next(item for item in tts_artifacts if item["id"] == first_dub_segment["audio_artifact_id"])
    artifact_path = storage_root / linked_artifact["storage_path"]
    assert artifact_path.exists()
    assert artifact_path.stat().st_size > 0

    event_types = {event["event_type"] for event in detail["events"]}
    for event_type in TTS_EVENTS:
        assert event_type in event_types

    with db_conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            select timeline_clip_id, character_id, text, provider, duration_ms, audio_artifact_id
            from dub_segments
            where project_id = %s
            order by created_at asc
            """,
            (project_id,),
        )
        rows = cur.fetchall()
        assert len(rows) == len(dub_segments)
        assert rows[0]["provider"] == "mock"
        assert rows[0]["audio_artifact_id"]

        cur.execute(
            """
            select artifact_type, storage_path
            from artifacts
            where project_id = %s and artifact_type = 'TTS_AUDIO'
            order by created_at asc
            """,
            (project_id,),
        )
        artifact_rows = cur.fetchall()
        assert artifact_rows
        assert all((storage_root / row["storage_path"]).exists() for row in artifact_rows)


def test_sprint10_failed_tts_job_does_not_break_api(client, auth_headers, db_conn, valid_sample_video_file: Path):
    project = create_project(client, auth_headers, name="Sprint 10 Failed TTS")
    project_id = project["id"]
    upload_video(client, auth_headers, project_id, valid_sample_video_file)
    detail = wait_for_pipeline_ready(client, auth_headers, project_id)

    first_clip = detail["timeline_clips"][0]
    proxy_artifact_id = first_clip["artifact_id"]

    with db_conn.cursor() as cur:
        cur.execute("delete from artifacts where id = %s", (proxy_artifact_id,))
        db_conn.commit()

    tts_response = client.post(f"/projects/{project_id}/tts", headers=auth_headers)
    assert tts_response.status_code == 200, tts_response.text

    import time

    failed_detail = None
    for _ in range(30):
        response = client.get(f"/projects/{project_id}", headers=auth_headers)
        assert response.status_code == 200, response.text
        failed_detail = response.json()
        jobs = {job["job_type"]: job for job in failed_detail["jobs"]}
        if "TTS" in jobs and jobs["TTS"]["state"] == "FAILED":
            break
        time.sleep(2)

    assert failed_detail is not None
    failed_jobs = {job["job_type"]: job for job in failed_detail["jobs"]}
    assert failed_jobs["TTS"]["state"] == "FAILED"
    assert "dub_segments" in failed_detail
    assert "artifacts" in failed_detail

    with db_conn.cursor(row_factory=dict_row) as cur:
        cur.execute("select error_json from jobs where id = %s", (failed_jobs["TTS"]["id"],))
        row = cur.fetchone()
        assert row["error_json"]

        cur.execute("select event_type from project_events where project_id = %s", (project_id,))
        event_types = {item["event_type"] for item in cur.fetchall()}
        assert "JOB_FAILED" in event_types
