from pathlib import Path

from psycopg.rows import dict_row


def create_project(client, auth_headers, name="Sprint 7 Acceptance Project"):
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


def wait_for_pipeline_ready(client, auth_headers, project_id: str, attempts: int = 90, delay_seconds: float = 2.0):
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
        ):
            return payload
        time.sleep(delay_seconds)
    raise AssertionError(f"Pipeline did not complete for project {project_id}")


def test_sprint7_character_layer_acceptance(client, auth_headers, db_conn, valid_sample_video_file):
    project = create_project(client, auth_headers)
    project_id = project["id"]
    upload_video(client, auth_headers, project_id, valid_sample_video_file)
    wait_for_pipeline_ready(client, auth_headers, project_id)

    response = client.post(f"/projects/{project_id}/characters/from-speakers", headers=auth_headers)
    assert response.status_code == 200, response.text
    detail = response.json()

    assert detail["characters"]
    assert detail["character_assignments"]
    assert all(clip["character_id"] for clip in detail["timeline_clips"] if clip["speaker_label"])

    character_count_before = len(detail["characters"])
    assignment_count_before = len(detail["character_assignments"])
    first_character = detail["characters"][0]

    rename_response = client.patch(
        f"/projects/{project_id}/characters/{first_character['id']}",
        headers=auth_headers,
        json={"display_name": "John", "description": "Lead speaker"},
    )
    assert rename_response.status_code == 200, rename_response.text
    renamed_detail = rename_response.json()
    renamed_character = next(item for item in renamed_detail["characters"] if item["id"] == first_character["id"])
    assert renamed_character["display_name"] == "John"

    second_response = client.post(f"/projects/{project_id}/characters/from-speakers", headers=auth_headers)
    assert second_response.status_code == 200, second_response.text
    second_detail = second_response.json()
    assert len(second_detail["characters"]) == character_count_before
    assert len(second_detail["character_assignments"]) == assignment_count_before

    with db_conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select display_name, source_type from characters where project_id = %s order by created_at asc",
            (project_id,),
        )
        characters = cur.fetchall()
        assert len(characters) == character_count_before
        assert characters[0]["display_name"] == "John"

        cur.execute(
            """
            select character_id, speaker_label, timeline_clip_id, assignment_source
            from character_assignments
            where project_id = %s
            order by created_at asc
            """,
            (project_id,),
        )
        assignments = cur.fetchall()
        assert len(assignments) == assignment_count_before
        assert any(row["speaker_label"] for row in assignments)
        assert any(row["timeline_clip_id"] for row in assignments)


def test_sprint7_character_failure_does_not_break_api(client, auth_headers, valid_sample_video_file):
    project = create_project(client, auth_headers, name="Sprint 7 Failure")
    project_id = project["id"]
    upload_video(client, auth_headers, project_id, valid_sample_video_file)
    wait_for_pipeline_ready(client, auth_headers, project_id)

    response = client.patch(
        f"/projects/{project_id}/characters/not-a-real-character",
        headers=auth_headers,
        json={"display_name": "Ghost", "description": "Should fail"},
    )
    assert response.status_code == 404, response.text

    detail = client.get(f"/projects/{project_id}", headers=auth_headers)
    assert detail.status_code == 200, detail.text
    payload = detail.json()
    assert "characters" in payload
    assert "character_assignments" in payload
