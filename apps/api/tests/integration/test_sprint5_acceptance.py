from pathlib import Path

from psycopg.rows import dict_row


TRANSLATION_EVENTS = {
    "TRANSLATION_STARTED",
    "TRANSLATION_SEGMENT_CREATED",
    "TRANSLATION_COMPLETED",
}


def create_project(client, auth_headers, name="Sprint 5 Acceptance Project"):
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


def wait_for_translation_ready(client, auth_headers, project_id: str, attempts: int = 70, delay_seconds: float = 2.0):
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
            and jobs_by_type["INGEST"]["state"] == "COMPLETED"
            and jobs_by_type["TRANSCRIBE"]["state"] == "COMPLETED"
            and jobs_by_type["TRANSLATE"]["state"] == "COMPLETED"
            and payload["transcript_segments"]
            and payload["translation_segments"]
        ):
            return payload
        time.sleep(delay_seconds)
    raise AssertionError(f"Translation pipeline did not complete for project {project_id}")


def test_sprint5_translation_layer_acceptance(client, auth_headers, db_conn, valid_sample_video_file):
    project = create_project(client, auth_headers)
    project_id = project["id"]
    upload_video(client, auth_headers, project_id, valid_sample_video_file)
    detail = wait_for_translation_ready(client, auth_headers, project_id)

    jobs = {job["job_type"]: job for job in detail["jobs"]}
    assert jobs["TRANSLATE"]["state"] == "COMPLETED"
    assert jobs["TRANSLATE"]["output_json"]["translation_segment_count"] >= 1
    assert jobs["TRANSLATE"]["output_json"]["provider"] == "mock"

    transcript_segments = detail["transcript_segments"]
    translation_segments = detail["translation_segments"]
    timeline_clips = detail["timeline_clips"]

    assert len(transcript_segments) == len(translation_segments)
    first_translation = translation_segments[0]
    assert first_translation["provider"] == "mock"
    assert first_translation["source_text"]
    assert first_translation["translated_text"]
    assert first_translation["target_language"] == "tr"

    first_clip = timeline_clips[0]
    assert first_clip["translation_segment_id"] == first_translation["id"]
    assert first_clip["metadata_json"]["translated_text"]

    event_types = {event["event_type"] for event in detail["events"]}
    for event_type in TRANSLATION_EVENTS:
        assert event_type in event_types

    with db_conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            select transcript_segment_id, source_language, target_language, source_text, translated_text, provider
            from translation_segments
            where project_id = %s
            order by created_at asc
            """,
            (project_id,),
        )
        rows = cur.fetchall()
        assert len(rows) == len(translation_segments)
        assert rows[0]["provider"] == "mock"
        assert rows[0]["translated_text"]


def test_sprint5_failed_translation_job_does_not_break_api(client, auth_headers, db_conn, valid_sample_video_file):
    project = create_project(client, auth_headers, name="Sprint 5 Failed Translation")
    project_id = project["id"]
    upload_video(client, auth_headers, project_id, valid_sample_video_file)
    detail = wait_for_translation_ready(client, auth_headers, project_id)

    jobs = {job["job_type"]: job for job in detail["jobs"]}
    translate_job_id = jobs["TRANSLATE"]["id"]

    with db_conn.cursor() as cur:
        cur.execute("delete from translation_segments where project_id = %s", (project_id,))
        cur.execute("delete from transcript_segments where project_id = %s", (project_id,))
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
            (translate_job_id,),
        )
        db_conn.commit()

    import time

    failed_detail = None
    for _ in range(30):
        response = client.get(f"/projects/{project_id}", headers=auth_headers)
        assert response.status_code == 200, response.text
        failed_detail = response.json()
        failed_jobs = {job["job_type"]: job for job in failed_detail["jobs"]}
        if failed_jobs["TRANSLATE"]["state"] == "FAILED":
            break
        time.sleep(2)

    assert failed_detail is not None
    failed_jobs = {job["job_type"]: job for job in failed_detail["jobs"]}
    assert failed_jobs["TRANSLATE"]["state"] == "FAILED"
    assert "transcript_segments" in failed_detail
    assert "translation_segments" in failed_detail

    with db_conn.cursor(row_factory=dict_row) as cur:
        cur.execute("select error_json from jobs where id = %s", (translate_job_id,))
        row = cur.fetchone()
        assert row["error_json"]

        cur.execute("select event_type from project_events where project_id = %s", (project_id,))
        event_types = {item["event_type"] for item in cur.fetchall()}
        assert "JOB_FAILED" in event_types
