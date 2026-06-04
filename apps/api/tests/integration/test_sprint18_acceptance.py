from pathlib import Path

from psycopg.rows import dict_row

from tests.integration.test_sprint10_acceptance import wait_for_tts_ready
from tests.integration.test_sprint11_acceptance import wait_for_audio_mix_ready
from tests.integration.test_sprint12_acceptance import wait_for_render_ready
from tests.integration.test_sprint7_acceptance import create_project, upload_video, wait_for_pipeline_ready


VOICE_CLONE_EVENTS = {
    "VOICE_SAMPLE_EXTRACTION_STARTED",
    "VOICE_SAMPLE_AUDIO_CREATED",
    "VOICE_PROFILE_CREATED_FROM_SAMPLE",
    "VOICE_PROFILE_ASSIGNED_TO_CHARACTER",
}


def wait_for_voice_sample_ready(client, auth_headers, project_id: str, attempts: int = 60, delay_seconds: float = 2.0):
    import time

    detail = None
    for _ in range(attempts):
        detail = client.get(f"/projects/{project_id}", headers=auth_headers)
        assert detail.status_code == 200, detail.text
        payload = detail.json()
        jobs_by_type = {job["job_type"]: job for job in payload["jobs"]}
        sample_artifacts = [
            artifact
            for artifact in payload["artifacts"]
            if artifact["artifact_type"] in {"VOICE_SAMPLE_AUDIO", "VOICE_REFERENCE_AUDIO"}
        ]
        if (
            "VOICE_SAMPLE_EXTRACT" in jobs_by_type
            and jobs_by_type["VOICE_SAMPLE_EXTRACT"]["state"] == "COMPLETED"
            and len(sample_artifacts) >= 2
        ):
            return payload
        time.sleep(delay_seconds)
    raise AssertionError(f"Voice sample extraction did not complete for project {project_id}")


def test_sprint18_voice_cloning_acceptance(client, auth_headers, db_conn, storage_root, valid_sample_video_file: Path):
    project = create_project(client, auth_headers, name="Sprint 18 Acceptance Project")
    project_id = project["id"]
    upload_video(client, auth_headers, project_id, valid_sample_video_file)
    wait_for_pipeline_ready(client, auth_headers, project_id)

    characters_response = client.post(f"/projects/{project_id}/characters/from-speakers", headers=auth_headers)
    assert characters_response.status_code == 200, characters_response.text
    detail = characters_response.json()
    assert detail["characters"]
    assert detail["timeline_clips"]

    first_character = detail["characters"][0]
    first_clip = next(
        clip for clip in detail["timeline_clips"] if clip["character_id"] == first_character["id"]
    )

    clip_update_response = client.patch(
        f"/projects/{project_id}/timeline/clips/{first_clip['id']}",
        headers=auth_headers,
        json={
            "translation_text": "Merhaba John.",
            "character_id": first_character["id"],
        },
    )
    assert clip_update_response.status_code == 200, clip_update_response.text

    sample_response = client.post(
        f"/projects/{project_id}/characters/{first_character['id']}/voice-sample",
        headers=auth_headers,
    )
    assert sample_response.status_code == 200, sample_response.text
    detail = wait_for_voice_sample_ready(client, auth_headers, project_id)

    jobs = {job["job_type"]: job for job in detail["jobs"]}
    assert jobs["VOICE_SAMPLE_EXTRACT"]["state"] == "COMPLETED"
    assert jobs["VOICE_SAMPLE_EXTRACT"]["output_json"]["voice_sample_artifact_id"]
    assert jobs["VOICE_SAMPLE_EXTRACT"]["output_json"]["voice_reference_artifact_id"]

    sample_artifact = next(artifact for artifact in detail["artifacts"] if artifact["artifact_type"] == "VOICE_SAMPLE_AUDIO")
    reference_artifact = next(artifact for artifact in detail["artifacts"] if artifact["artifact_type"] == "VOICE_REFERENCE_AUDIO")
    assert (storage_root / sample_artifact["storage_path"]).exists()
    assert (storage_root / reference_artifact["storage_path"]).exists()
    assert sample_artifact["parent_artifact_ids"]
    assert reference_artifact["parent_artifact_ids"] == [sample_artifact["id"]]

    cloned_profile_response = client.post(
        f"/projects/{project_id}/characters/{first_character['id']}/voice-profile/from-sample",
        headers=auth_headers,
    )
    assert cloned_profile_response.status_code == 200, cloned_profile_response.text
    detail = cloned_profile_response.json()

    character_after_clone = next(item for item in detail["characters"] if item["id"] == first_character["id"])
    assert character_after_clone["assigned_voice_profile_id"]
    assert character_after_clone["assigned_voice_profile"]
    assert character_after_clone["assigned_voice_profile"]["profile_type"] == "cloned"
    assert character_after_clone["assigned_voice_profile"]["reference_audio_artifact_id"] == reference_artifact["id"]
    assert character_after_clone["assigned_voice_profile"]["source_character_id"] == first_character["id"]
    assert character_after_clone["assigned_voice_profile"]["status"] == "ready"

    tts_response = client.post(f"/projects/{project_id}/tts", headers=auth_headers)
    assert tts_response.status_code == 200, tts_response.text
    detail = wait_for_tts_ready(client, auth_headers, project_id)

    tts_jobs = {job["job_type"]: job for job in detail["jobs"]}
    assert tts_jobs["TTS"]["state"] == "COMPLETED"

    cloned_segment = next(item for item in detail["dub_segments"] if item["timeline_clip_id"] == first_clip["id"])
    assert cloned_segment["provider"] == "mock_voice_clone"
    assert cloned_segment["voice_profile_id"] == character_after_clone["assigned_voice_profile_id"]
    assert cloned_segment["metadata_json"]["voice_profile_type"] == "cloned"
    assert cloned_segment["audio_artifact_id"]

    tts_artifact = next(artifact for artifact in detail["artifacts"] if artifact["id"] == cloned_segment["audio_artifact_id"])
    assert tts_artifact["artifact_type"] == "TTS_AUDIO"
    assert (storage_root / tts_artifact["storage_path"]).exists()

    mix_response = client.post(f"/projects/{project_id}/audio-mix", headers=auth_headers)
    assert mix_response.status_code == 200, mix_response.text
    wait_for_audio_mix_ready(client, auth_headers, project_id)

    render_response = client.post(f"/projects/{project_id}/render", headers=auth_headers)
    assert render_response.status_code == 200, render_response.text
    detail = wait_for_render_ready(client, auth_headers, project_id)

    final_render = next(artifact for artifact in detail["artifacts"] if artifact["artifact_type"] == "FINAL_RENDER")
    assert (storage_root / final_render["storage_path"]).exists()

    event_types = {event["event_type"] for event in detail["events"]}
    for event_type in VOICE_CLONE_EVENTS:
        assert event_type in event_types

    with db_conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            select profile_type, provider, reference_audio_artifact_id, source_character_id, status
            from voice_profiles
            where id = %s
            """,
            (character_after_clone["assigned_voice_profile_id"],),
        )
        profile_row = cur.fetchone()
        assert profile_row["profile_type"] == "cloned"
        assert profile_row["provider"] == "mock"
        assert str(profile_row["reference_audio_artifact_id"]) == reference_artifact["id"]
        assert str(profile_row["source_character_id"]) == first_character["id"]
        assert profile_row["status"] == "ready"

        cur.execute(
            """
            select provider, voice_profile_id, metadata_json
            from dub_segments
            where project_id = %s and timeline_clip_id = %s
            """,
            (project_id, first_clip["id"]),
        )
        dub_row = cur.fetchone()
        assert dub_row["provider"] == "mock_voice_clone"
        assert str(dub_row["voice_profile_id"]) == character_after_clone["assigned_voice_profile_id"]
        assert dub_row["metadata_json"]["voice_profile_type"] == "cloned"


def test_sprint18_missing_character_segments_returns_400(client, auth_headers, valid_sample_video_file: Path):
    project = create_project(client, auth_headers, name="Sprint 18 Missing Character Segments")
    project_id = project["id"]
    upload_video(client, auth_headers, project_id, valid_sample_video_file)
    wait_for_pipeline_ready(client, auth_headers, project_id)

    characters_response = client.post(f"/projects/{project_id}/characters/from-speakers", headers=auth_headers)
    assert characters_response.status_code == 200, characters_response.text
    detail = characters_response.json()
    first_character = detail["characters"][0]

    for clip in detail["timeline_clips"]:
        if clip["character_id"] != first_character["id"]:
            continue
        update_response = client.patch(
            f"/projects/{project_id}/timeline/clips/{clip['id']}",
            headers=auth_headers,
            json={"character_id": None},
        )
        assert update_response.status_code == 200, update_response.text

    sample_response = client.post(
        f"/projects/{project_id}/characters/{first_character['id']}/voice-sample",
        headers=auth_headers,
    )
    assert sample_response.status_code == 400, sample_response.text
    payload = sample_response.json()
    assert payload["error"]["code"] == "VOICE_SAMPLE_SOURCE_SEGMENTS_NOT_FOUND"

    detail_response = client.get(f"/projects/{project_id}", headers=auth_headers)
    assert detail_response.status_code == 200, detail_response.text
    project_detail = detail_response.json()
    assert "characters" in project_detail
    assert "timeline_clips" in project_detail
