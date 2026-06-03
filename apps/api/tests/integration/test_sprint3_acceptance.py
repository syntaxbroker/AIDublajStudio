from pathlib import Path

from psycopg.rows import dict_row


TRANSCRIPT_EVENTS = {
    "TRANSCRIPTION_STARTED",
    "TRANSCRIPTION_SEGMENT_CREATED",
    "TRANSCRIPTION_COMPLETED",
    "TIMELINE_CLIPS_CREATED",
}


def create_project(client, auth_headers, name="Sprint 3 Acceptance Project"):
    response = client.post(
        "/projects",
        headers=auth_headers,
        json={"name": name, "source_language": "en", "target_language": "tr"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def upload_video(client, auth_headers, project_id, path: Path):
    with path.open("rb") as handle:
        response = client.post(
            f"/projects/{project_id}/upload",
            headers=auth_headers,
            files={"file": (path.name, handle, "video/mp4")},
        )
    assert response.status_code == 200, response.text
    return response.json()


def wait_for_transcription_ready(client, auth_headers, project_id: str, attempts: int = 50, delay_seconds: float = 2.0):
    import time

    detail = None
    for _ in range(attempts):
        detail = client.get(f"/projects/{project_id}", headers=auth_headers)
        assert detail.status_code == 200, detail.text
        payload = detail.json()
        jobs_by_type = {job["job_type"]: job for job in payload["jobs"]}
        if (
            "INGEST" in jobs_by_type
            and "TRANSCRIBE" in jobs_by_type
            and jobs_by_type["INGEST"]["state"] == "COMPLETED"
            and jobs_by_type["TRANSCRIBE"]["state"] == "COMPLETED"
            and payload["transcript_segments"]
            and payload["timeline_clips"]
        ):
            return payload
        time.sleep(delay_seconds)
    raise AssertionError(f"Transcription pipeline did not complete for project {project_id}")


def test_sprint3_mock_asr_acceptance(client, auth_headers, db_conn, valid_sample_video_file, storage_root):
    project = create_project(client, auth_headers)
    project_id = project["id"]
    upload_video(client, auth_headers, project_id, valid_sample_video_file)
    detail = wait_for_transcription_ready(client, auth_headers, project_id)

    artifacts = {artifact["artifact_type"]: artifact for artifact in detail["artifacts"]}
    assert "PROXY_VIDEO" in artifacts

    jobs = {job["job_type"]: job for job in detail["jobs"]}
    assert jobs["INGEST"]["state"] == "COMPLETED"
    assert jobs["INGEST"]["output_json"]["media_stage"] == "READY_FOR_TRANSCRIPTION"
    assert jobs["TRANSCRIBE"]["state"] == "COMPLETED"
    assert jobs["TRANSCRIBE"]["output_json"]["segment_count"] >= 1
    assert jobs["TRANSCRIBE"]["output_json"]["timeline_clip_count"] >= 1

    transcript_segments = detail["transcript_segments"]
    timeline_clips = detail["timeline_clips"]
    assert len(transcript_segments) >= 1
    assert len(timeline_clips) >= 1

    first_segment = transcript_segments[0]
    assert first_segment["start_ms"] < first_segment["end_ms"]
    assert first_segment["text"]

    first_clip = timeline_clips[0]
    assert first_clip["clip_type"] == "DIALOG"
    assert first_clip["transcript_segment_id"] == first_segment["id"]

    proxy_path = storage_root / artifacts["PROXY_VIDEO"]["storage_path"]
    assert proxy_path.exists()

    event_types = {event["event_type"] for event in detail["events"]}
    for event_type in TRANSCRIPT_EVENTS:
        assert event_type in event_types

    with db_conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            select id, project_id, source_artifact_id, segment_index, start_ms, end_ms, text
            from transcript_segments
            where project_id = %s
            order by segment_index asc
            """,
            (project_id,),
        )
        segment_rows = cur.fetchall()
        assert len(segment_rows) == len(transcript_segments)
        assert all(str(row["source_artifact_id"]) == artifacts["PROXY_VIDEO"]["id"] for row in segment_rows)

        cur.execute(
            """
            select id, project_id, transcript_segment_id, artifact_id, clip_type, start_ms, end_ms
            from timeline_clips
            where project_id = %s
            order by start_ms asc
            """,
            (project_id,),
        )
        clip_rows = cur.fetchall()
        assert len(clip_rows) == len(timeline_clips)
        assert all(str(row["artifact_id"]) == artifacts["PROXY_VIDEO"]["id"] for row in clip_rows)

        cur.execute(
            """
            select event_type
            from project_events
            where project_id = %s
            """,
            (project_id,),
        )
        db_event_types = {row["event_type"] for row in cur.fetchall()}
        for event_type in TRANSCRIPT_EVENTS:
            assert event_type in db_event_types


def test_sprint3_missing_proxy_fails_cleanly(client, auth_headers, db_conn, valid_sample_video_file):
    project = create_project(client, auth_headers, name="Sprint 3 Missing Proxy")
    project_id = project["id"]
    upload_video(client, auth_headers, project_id, valid_sample_video_file)
    detail = wait_for_transcription_ready(client, auth_headers, project_id)

    jobs = {job["job_type"]: job for job in detail["jobs"]}
    transcribe_job_id = jobs["TRANSCRIBE"]["id"]
    proxy_artifact_id = jobs["TRANSCRIBE"]["input_json"]["artifact_id"]

    with db_conn.cursor() as cur:
        cur.execute("delete from timeline_clips where project_id = %s", (project_id,))
        cur.execute("delete from transcript_segments where project_id = %s", (project_id,))
        cur.execute("delete from artifacts where id = %s", (proxy_artifact_id,))
        cur.execute(
            """
            update jobs
            set state = 'QUEUED',
                worker_name = null,
                started_at = null,
                completed_at = null,
                updated_at = now(),
                output_json = '{}'::jsonb,
                error_json = null
            where id = %s
            """,
            (transcribe_job_id,),
        )
        db_conn.commit()

    import time

    failed_detail = None
    for _ in range(30):
        response = client.get(f"/projects/{project_id}", headers=auth_headers)
        assert response.status_code == 200, response.text
        failed_detail = response.json()
        failed_jobs = {job["job_type"]: job for job in failed_detail["jobs"]}
        if failed_jobs["TRANSCRIBE"]["state"] == "FAILED":
            break
        time.sleep(2)

    assert failed_detail is not None
    failed_jobs = {job["job_type"]: job for job in failed_detail["jobs"]}
    assert failed_jobs["TRANSCRIBE"]["state"] == "FAILED"
    assert failed_detail["artifacts"]

    with db_conn.cursor(row_factory=dict_row) as cur:
        cur.execute("select error_json from jobs where id = %s", (transcribe_job_id,))
        row = cur.fetchone()
        assert row["error_json"]

        cur.execute(
            "select event_type from project_events where project_id = %s order by created_at desc",
            (project_id,),
        )
        event_types = {item["event_type"] for item in cur.fetchall()}
        assert "JOB_FAILED" in event_types
