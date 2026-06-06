from pathlib import Path

from psycopg.rows import dict_row

from tests.integration.test_sprint10_acceptance import wait_for_tts_ready
from tests.integration.test_sprint6_acceptance import wait_for_diarization_ready
from tests.integration.test_sprint7_acceptance import create_project, upload_video


def test_sprint16_voice_profile_acceptance(client, auth_headers, db_conn, valid_sample_video_file: Path):
    voice_profiles_response = client.get("/voice-profiles", headers=auth_headers)
    assert voice_profiles_response.status_code == 200, voice_profiles_response.text
    voice_profiles = voice_profiles_response.json()
    assert voice_profiles
    default_profile = next(profile for profile in voice_profiles if profile["voice_id"] == "tr-TR-AhmetNeural")

    project = create_project(client, auth_headers, name="Sprint 16 Acceptance Project")
    project_id = project["id"]
    upload_video(client, auth_headers, project_id, valid_sample_video_file)
    wait_for_diarization_ready(client, auth_headers, project_id)

    characters_response = client.post(f"/projects/{project_id}/characters/from-speakers", headers=auth_headers)
    assert characters_response.status_code == 200, characters_response.text
    detail = characters_response.json()
    assert detail["characters"]
    first_character = detail["characters"][0]
    first_clip = detail["timeline_clips"][0]

    split_at_ms = first_clip["start_ms"] + max(1, (first_clip["end_ms"] - first_clip["start_ms"]) // 2)
    split_response = client.post(
        f"/projects/{project_id}/timeline/clips/{first_clip['id']}/split",
        headers=auth_headers,
        json={"split_at_ms": split_at_ms},
    )
    assert split_response.status_code == 200, split_response.text
    split_timeline = split_response.json()["clips"]
    first_clip_after_split = next(item for item in split_timeline if item["id"] == first_clip["id"])
    second_clip = next(item for item in split_timeline if item["id"] != first_clip["id"])

    first_update = client.patch(
        f"/projects/{project_id}/timeline/clips/{first_clip_after_split['id']}",
        headers=auth_headers,
        json={
            "translation_text": "Merhaba John.",
            "character_id": first_character["id"],
        },
    )
    assert first_update.status_code == 200, first_update.text

    second_update = client.patch(
        f"/projects/{project_id}/timeline/clips/{second_clip['id']}",
        headers=auth_headers,
        json={
            "translation_text": "Nasılsın?",
            "character_id": None,
        },
    )
    assert second_update.status_code == 200, second_update.text

    assignment_response = client.post(
        f"/projects/{project_id}/characters/{first_character['id']}/voice-profile",
        headers=auth_headers,
        json={"voice_profile_id": default_profile["id"]},
    )
    assert assignment_response.status_code == 200, assignment_response.text
    assigned_detail = assignment_response.json()
    assigned_character = next(item for item in assigned_detail["characters"] if item["id"] == first_character["id"])
    assert assigned_character["assigned_voice_profile_id"] == default_profile["id"]
    assert assigned_character["assigned_voice_profile"]["voice_id"] == default_profile["voice_id"]

    tts_response = client.post(f"/projects/{project_id}/tts", headers=auth_headers)
    assert tts_response.status_code == 200, tts_response.text

    detail = wait_for_tts_ready(client, auth_headers, project_id)
    jobs = {job["job_type"]: job for job in detail["jobs"]}
    assert jobs["TTS"]["state"] == "COMPLETED"
    assert jobs["TTS"]["output_json"]["provider"] == "mock"

    dub_segments = detail["dub_segments"]
    assigned_segment = next(item for item in dub_segments if item["timeline_clip_id"] == first_clip_after_split["id"])
    fallback_segment = next(item for item in dub_segments if item["timeline_clip_id"] == second_clip["id"])
    assert assigned_segment["voice_profile_id"] == default_profile["id"]
    assert assigned_segment["metadata_json"]["voice_name"] == default_profile["voice_id"]
    assert assigned_segment["metadata_json"]["voice_selection_source"] == "character_assignment"
    assert fallback_segment["voice_profile_id"] == default_profile["id"]
    assert fallback_segment["metadata_json"]["voice_name"] == default_profile["voice_id"]
    assert fallback_segment["metadata_json"]["voice_selection_source"] in {"shared_language_default", "provider_default"}

    tts_artifacts = [artifact for artifact in detail["artifacts"] if artifact["artifact_type"] == "TTS_AUDIO"]
    assert len(tts_artifacts) >= 2

    with db_conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            select cva.character_id, cva.voice_profile_id, vp.voice_id
            from character_voice_assignments cva
            join voice_profiles vp on vp.id = cva.voice_profile_id
            where cva.project_id = %s
            """,
            (project_id,),
        )
        assignment_rows = cur.fetchall()
        assert assignment_rows
        assert str(assignment_rows[0]["character_id"]) == first_character["id"]
        assert str(assignment_rows[0]["voice_profile_id"]) == default_profile["id"]
        assert assignment_rows[0]["voice_id"] == default_profile["voice_id"]

        cur.execute(
            """
            select timeline_clip_id, voice_profile_id, metadata_json
            from dub_segments
            where project_id = %s
            order by created_at asc
            """,
            (project_id,),
        )
        dub_rows = cur.fetchall()
        assert any(str(row["voice_profile_id"]) == default_profile["id"] for row in dub_rows)
        assert any(row["metadata_json"]["voice_name"] == default_profile["voice_id"] for row in dub_rows)


def test_sprint16_invalid_voice_profile_returns_404(client, auth_headers, valid_sample_video_file: Path):
    project = create_project(client, auth_headers, name="Sprint 16 Invalid Voice Profile")
    project_id = project["id"]
    upload_video(client, auth_headers, project_id, valid_sample_video_file)
    wait_for_diarization_ready(client, auth_headers, project_id)

    characters_response = client.post(f"/projects/{project_id}/characters/from-speakers", headers=auth_headers)
    assert characters_response.status_code == 200, characters_response.text
    character_id = characters_response.json()["characters"][0]["id"]

    assignment_response = client.post(
        f"/projects/{project_id}/characters/{character_id}/voice-profile",
        headers=auth_headers,
        json={"voice_profile_id": "00000000-0000-0000-0000-000000000099"},
    )
    assert assignment_response.status_code == 404, assignment_response.text

    detail = client.get(f"/projects/{project_id}", headers=auth_headers)
    assert detail.status_code == 200, detail.text
    payload = detail.json()
    assert "characters" in payload
    assert "timeline_clips" in payload
