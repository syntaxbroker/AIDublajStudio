import os

import pytest


def create_project(client, auth_headers, name="Sprint 1 Project"):
    response = client.post(
        "/projects",
        headers=auth_headers,
        json={"name": name, "source_language": "en", "target_language": "tr"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def upload_video(client, auth_headers, project_id, path):
    with path.open("rb") as handle:
        response = client.post(
            f"/projects/{project_id}/upload",
            headers=auth_headers,
            files={"file": (path.name, handle, "video/mp4")},
        )
    return response


def test_auth_project_upload_and_detail_flow(client, auth_headers, temp_video_file):
    project = create_project(client, auth_headers)
    project_id = project["id"]

    upload_response = upload_video(client, auth_headers, project_id, temp_video_file)
    assert upload_response.status_code == 200, upload_response.text

    detail_response = client.get(f"/projects/{project_id}", headers=auth_headers)
    assert detail_response.status_code == 200, detail_response.text
    detail = detail_response.json()

    assert detail["id"] == project_id
    assert len(detail["artifacts"]) == 1
    assert detail["artifacts"][0]["artifact_type"] == "SOURCE_VIDEO"
    assert detail["artifacts"][0]["checksum_sha256"]
    assert len(detail["jobs"]) == 1
    assert detail["jobs"][0]["job_type"] == "INGEST"
    assert detail["jobs"][0]["state"] == "QUEUED"
    event_types = [event["event_type"] for event in detail["events"]]
    assert "PROJECT_CREATED" in event_types
    assert "UPLOAD_STARTED" in event_types
    assert "VIDEO_UPLOADED" in event_types
    assert "JOB_STATE_CHANGED" in event_types


def test_duplicate_upload_returns_conflict(client, auth_headers, temp_video_file):
    project = create_project(client, auth_headers, name="Duplicate Upload Project")
    project_id = project["id"]

    first = upload_video(client, auth_headers, project_id, temp_video_file)
    assert first.status_code == 200, first.text

    second = upload_video(client, auth_headers, project_id, temp_video_file)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "DUPLICATE_ARTIFACT"


def test_large_filename_upload(client, auth_headers, exotic_filename_video):
    project = create_project(client, auth_headers, name="Filename Project")
    project_id = project["id"]

    response = upload_video(client, auth_headers, project_id, exotic_filename_video)
    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["artifacts"][0]["file_name"] == exotic_filename_video.name


@pytest.mark.slow
def test_large_upload_one_gb(client, auth_headers, tmp_path):
    if os.getenv("RUN_LARGE_UPLOAD") != "1":
        pytest.skip("Set RUN_LARGE_UPLOAD=1 to run the 1 GB upload test")

    sparse_file = tmp_path / "large-upload.mp4"
    with sparse_file.open("wb") as handle:
        handle.seek((1024 * 1024 * 1024) - 1)
        handle.write(b"\0")

    project = create_project(client, auth_headers, name="Large Upload Project")
    response = upload_video(client, auth_headers, project["id"], sparse_file)
    assert response.status_code == 200, response.text
