from pathlib import Path

from psycopg.rows import dict_row


MEDIA_ARTIFACT_TYPES = {
    "VIDEO_METADATA",
    "THUMBNAIL",
    "PROXY_VIDEO",
    "WAVEFORM_JSON",
}


def create_project(client, auth_headers, name="Sprint 2 Acceptance Project"):
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


def wait_for_media_ready(client, auth_headers, project_id: str, attempts: int = 40, delay_seconds: float = 2.0):
    import time

    detail = None
    for _ in range(attempts):
        detail = client.get(f"/projects/{project_id}", headers=auth_headers)
        assert detail.status_code == 200, detail.text
        payload = detail.json()
        artifact_types = {artifact["artifact_type"] for artifact in payload["artifacts"]}
        if MEDIA_ARTIFACT_TYPES.issubset(artifact_types) and payload["jobs"] and payload["jobs"][0]["state"] == "COMPLETED":
            return payload
        time.sleep(delay_seconds)
    raise AssertionError(f"Media pipeline did not complete for project {project_id}")


def test_sprint2_media_pipeline_acceptance(client, auth_headers, db_conn, valid_sample_video_file, storage_root):
    project = create_project(client, auth_headers)
    project_id = project["id"]
    upload_video(client, auth_headers, project_id, valid_sample_video_file)
    detail = wait_for_media_ready(client, auth_headers, project_id)

    artifacts = detail["artifacts"]
    artifact_by_type = {artifact["artifact_type"]: artifact for artifact in artifacts}
    assert "SOURCE_VIDEO" in artifact_by_type
    assert MEDIA_ARTIFACT_TYPES.issubset(set(artifact_by_type))

    source_id = artifact_by_type["SOURCE_VIDEO"]["id"]
    for artifact_type in MEDIA_ARTIFACT_TYPES:
        assert artifact_by_type[artifact_type]["parent_artifact_ids"] == [source_id]

    for artifact in artifacts:
        storage_path = artifact["storage_path"]
        absolute_path = storage_root / storage_path
        assert absolute_path.exists(), f"Missing file on disk: {absolute_path}"

    assert detail["jobs"][0]["job_type"] == "INGEST"
    assert detail["jobs"][0]["state"] == "COMPLETED"
    assert detail["jobs"][0]["output_json"]["media_stage"] == "READY_FOR_TRANSCRIPTION"

    event_types = {event["event_type"] for event in detail["events"]}
    assert "METADATA_EXTRACTED" in event_types
    assert "THUMBNAIL_GENERATED" in event_types
    assert "PROXY_GENERATED" in event_types
    assert "WAVEFORM_GENERATED" in event_types
    assert "MEDIA_READY_FOR_TRANSCRIPTION" in event_types

    with db_conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            select a.artifact_type, a.storage_path, l.parent_artifact_id, a.created_by_job_id
            from artifacts a
            left join artifact_links l on l.child_artifact_id = a.id
            where a.project_id = %s
            order by a.created_at desc
            """,
            (project_id,),
        )
        rows = cur.fetchall()
        assert rows
        parent_map = {row["artifact_type"]: row["parent_artifact_id"] for row in rows if row["artifact_type"] != "SOURCE_VIDEO"}
        for artifact_type in MEDIA_ARTIFACT_TYPES:
            assert str(parent_map[artifact_type]) == source_id

        cur.execute(
            """
            select event_type
            from project_events
            where project_id = %s
            """,
            (project_id,),
        )
        db_event_types = {row["event_type"] for row in cur.fetchall()}
        for expected in [
            "METADATA_EXTRACTED",
            "THUMBNAIL_GENERATED",
            "PROXY_GENERATED",
            "WAVEFORM_GENERATED",
            "MEDIA_READY_FOR_TRANSCRIPTION",
        ]:
            assert expected in db_event_types


def test_sprint2_faulty_video_fails_cleanly(client, auth_headers, db_conn, tmp_path):
    broken_video = tmp_path / "broken.mp4"
    broken_video.write_bytes(b"not-a-real-mp4")

    project = create_project(client, auth_headers, name="Sprint 2 Broken Video")
    project_id = project["id"]
    upload_video(client, auth_headers, project_id, broken_video)

    import time

    detail = None
    for _ in range(30):
        response = client.get(f"/projects/{project_id}", headers=auth_headers)
        assert response.status_code == 200, response.text
        detail = response.json()
        if detail["jobs"] and detail["jobs"][0]["state"] == "FAILED":
            break
        time.sleep(2)

    assert detail is not None
    assert detail["jobs"][0]["state"] == "FAILED"

    with db_conn.cursor(row_factory=dict_row) as cur:
        cur.execute("select error_json from jobs where id = %s", (detail["jobs"][0]["id"],))
        job_row = cur.fetchone()
        assert job_row["error_json"]

        cur.execute(
            "select event_type, payload_json from project_events where project_id = %s order by created_at desc",
            (project_id,),
        )
        rows = cur.fetchall()
        event_types = {row["event_type"] for row in rows}
        assert "JOB_FAILED" in event_types
