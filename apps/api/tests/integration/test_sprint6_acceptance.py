from pathlib import Path

from psycopg.rows import dict_row


DIARIZATION_EVENTS = {
    "DIARIZATION_STARTED",
    "SPEAKER_SEGMENT_CREATED",
    "DIARIZATION_COMPLETED",
    "TRANSCRIPT_SPEAKER_ASSIGNED",
}


def create_project(client, auth_headers, name="Sprint 6 Acceptance Project"):
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


def wait_for_diarization_ready(client, auth_headers, project_id: str, attempts: int = 80, delay_seconds: float = 2.0):
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
            and "TRANSLATE" in jobs_by_type
            and "DIARIZE" in jobs_by_type
            and jobs_by_type["INGEST"]["state"] == "COMPLETED"
            and jobs_by_type["TRANSCRIBE"]["state"] == "COMPLETED"
            and jobs_by_type["TRANSLATE"]["state"] == "COMPLETED"
            and jobs_by_type["DIARIZE"]["state"] == "COMPLETED"
            and payload["speaker_segments"]
            and payload["transcript_segments"]
        ):
            return payload
        time.sleep(delay_seconds)
    raise AssertionError(f"Diarization pipeline did not complete for project {project_id}")


def test_sprint6_diarization_layer_acceptance(client, auth_headers, db_conn, valid_sample_video_file):
    project = create_project(client, auth_headers)
    project_id = project["id"]
    upload_video(client, auth_headers, project_id, valid_sample_video_file)
    detail = wait_for_diarization_ready(client, auth_headers, project_id)

    jobs = {job["job_type"]: job for job in detail["jobs"]}
    assert jobs["TRANSLATE"]["state"] == "COMPLETED"
    assert jobs["DIARIZE"]["state"] == "COMPLETED"
    assert jobs["DIARIZE"]["output_json"]["speaker_segment_count"] >= 1

    speaker_segments = detail["speaker_segments"]
    transcript_segments = detail["transcript_segments"]
    timeline_clips = detail["timeline_clips"]

    assert len(speaker_segments) >= 1
    assert all(segment["speaker_label"] for segment in speaker_segments)
    assert all(segment["speaker_label"] for segment in transcript_segments)
    assert all(clip["speaker_label"] for clip in timeline_clips)

    event_types = {event["event_type"] for event in detail["events"]}
    for event_type in DIARIZATION_EVENTS:
        assert event_type in event_types

    with db_conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            select start_ms, end_ms, speaker_label, provider
            from speaker_segments
            where project_id = %s
            order by start_ms asc
            """,
            (project_id,),
        )
        rows = cur.fetchall()
        assert len(rows) == len(speaker_segments)
        assert rows[0]["provider"] == "mock"

        cur.execute(
            """
            select speaker_label
            from transcript_segments
            where project_id = %s
            order by segment_index asc
            """,
            (project_id,),
        )
        transcript_rows = cur.fetchall()
        assert transcript_rows
        assert all(row["speaker_label"] for row in transcript_rows)


def test_sprint6_failed_diarization_job_does_not_break_api(client, auth_headers, db_conn, valid_sample_video_file):
    project = create_project(client, auth_headers, name="Sprint 6 Failed Diarization")
    project_id = project["id"]
    upload_video(client, auth_headers, project_id, valid_sample_video_file)
    detail = wait_for_diarization_ready(client, auth_headers, project_id)

    jobs = {job["job_type"]: job for job in detail["jobs"]}
    diarize_job_id = jobs["DIARIZE"]["id"]
    proxy_artifact_id = jobs["DIARIZE"]["input_json"]["artifact_id"]

    with db_conn.cursor() as cur:
        cur.execute("delete from speaker_segments where project_id = %s", (project_id,))
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
            (diarize_job_id,),
        )
        db_conn.commit()

    import time

    failed_detail = None
    for _ in range(30):
        response = client.get(f"/projects/{project_id}", headers=auth_headers)
        assert response.status_code == 200, response.text
        failed_detail = response.json()
        failed_jobs = {job["job_type"]: job for job in failed_detail["jobs"]}
        if failed_jobs["DIARIZE"]["state"] == "FAILED":
            break
        time.sleep(2)

    assert failed_detail is not None
    failed_jobs = {job["job_type"]: job for job in failed_detail["jobs"]}
    assert failed_jobs["DIARIZE"]["state"] == "FAILED"
    assert "speaker_segments" in failed_detail

    with db_conn.cursor(row_factory=dict_row) as cur:
        cur.execute("select error_json from jobs where id = %s", (diarize_job_id,))
        row = cur.fetchone()
        assert row["error_json"]

        cur.execute("select event_type from project_events where project_id = %s", (project_id,))
        event_types = {item["event_type"] for item in cur.fetchall()}
        assert "JOB_FAILED" in event_types
