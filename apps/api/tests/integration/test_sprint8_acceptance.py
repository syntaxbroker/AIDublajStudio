from psycopg.rows import dict_row

from tests.integration.test_sprint7_acceptance import create_project, upload_video, wait_for_pipeline_ready


TIMELINE_EVENTS = {
    "TIMELINE_CLIP_UPDATED",
    "TIMELINE_CLIP_SPLIT",
    "TIMELINE_CLIPS_MERGED",
}


def test_sprint8_timeline_edit_acceptance(client, auth_headers, db_conn, valid_sample_video_file):
    project = create_project(client, auth_headers, name="Sprint 8 Acceptance Project")
    project_id = project["id"]
    upload_video(client, auth_headers, project_id, valid_sample_video_file)
    wait_for_pipeline_ready(client, auth_headers, project_id)

    characters_response = client.post(f"/projects/{project_id}/characters/from-speakers", headers=auth_headers)
    assert characters_response.status_code == 200, characters_response.text
    characters_detail = characters_response.json()
    characters = characters_detail["characters"]
    assert len(characters) >= 2

    timeline_response = client.get(f"/projects/{project_id}/timeline", headers=auth_headers)
    assert timeline_response.status_code == 200, timeline_response.text
    timeline = timeline_response.json()
    clips = timeline["clips"]
    assert len(clips) >= 3

    first_clip = clips[0]
    second_clip = clips[1]
    third_clip = clips[2]
    replacement_character_id = characters[1]["id"]

    update_response = client.patch(
        f"/projects/{project_id}/timeline/clips/{first_clip['id']}",
        headers=auth_headers,
        json={
            "text": "Hello John.",
            "translation_text": "Merhaba John.",
            "character_id": replacement_character_id,
            "speaker_label": "speaker_custom",
        },
    )
    assert update_response.status_code == 200, update_response.text
    updated_timeline = update_response.json()
    updated_clip = next(item for item in updated_timeline["clips"] if item["id"] == first_clip["id"])
    assert updated_clip["text"] == "Hello John."
    assert updated_clip["translation_text"] == "Merhaba John."
    assert updated_clip["character_id"] == replacement_character_id
    assert updated_clip["speaker_label"] == "speaker_custom"
    assert updated_clip["edited_by_user_id"]
    assert updated_clip["edited_at"]
    assert updated_clip["edit_version"] >= 1

    overlap_response = client.patch(
        f"/projects/{project_id}/timeline/clips/{first_clip['id']}",
        headers=auth_headers,
        json={"end_ms": second_clip["start_ms"] + 200},
    )
    assert overlap_response.status_code == 409, overlap_response.text

    invalid_character_response = client.patch(
        f"/projects/{project_id}/timeline/clips/{first_clip['id']}",
        headers=auth_headers,
        json={"character_id": "not-a-real-character"},
    )
    assert invalid_character_response.status_code == 404, invalid_character_response.text

    split_at_ms = (third_clip["start_ms"] + third_clip["end_ms"]) // 2
    split_response = client.post(
        f"/projects/{project_id}/timeline/clips/{third_clip['id']}/split",
        headers=auth_headers,
        json={"split_at_ms": split_at_ms},
    )
    assert split_response.status_code == 200, split_response.text
    split_timeline = split_response.json()
    assert len(split_timeline["clips"]) == len(clips) + 1

    split_clips = sorted(
        [
            item
            for item in split_timeline["clips"]
            if item["transcript_segment_id"] == third_clip["transcript_segment_id"]
            and item["start_ms"] >= third_clip["start_ms"]
            and item["end_ms"] <= third_clip["end_ms"]
        ],
        key=lambda item: item["start_ms"],
    )
    assert len(split_clips) == 2
    assert split_clips[0]["end_ms"] == split_at_ms
    assert split_clips[1]["start_ms"] == split_at_ms

    merge_response = client.post(
        f"/projects/{project_id}/timeline/clips/merge",
        headers=auth_headers,
        json={"clip_ids": [split_clips[0]["id"], split_clips[1]["id"]]},
    )
    assert merge_response.status_code == 200, merge_response.text
    merged_timeline = merge_response.json()
    assert len(merged_timeline["clips"]) == len(clips)
    merged_clip = next(item for item in merged_timeline["clips"] if item["id"] == split_clips[0]["id"])
    assert merged_clip["start_ms"] == third_clip["start_ms"]
    assert merged_clip["end_ms"] == third_clip["end_ms"]
    assert merged_clip["text"] == third_clip["text"]

    persisted_timeline = client.get(f"/projects/{project_id}/timeline", headers=auth_headers)
    assert persisted_timeline.status_code == 200, persisted_timeline.text
    persisted_payload = persisted_timeline.json()
    persisted_first_clip = next(item for item in persisted_payload["clips"] if item["id"] == first_clip["id"])
    assert persisted_first_clip["text"] == "Hello John."
    assert persisted_first_clip["translation_text"] == "Merhaba John."
    assert persisted_first_clip["character_id"] == replacement_character_id

    detail_response = client.get(f"/projects/{project_id}", headers=auth_headers)
    assert detail_response.status_code == 200, detail_response.text
    project_detail = detail_response.json()
    detail_first_clip = next(item for item in project_detail["timeline_clips"] if item["id"] == first_clip["id"])
    assert detail_first_clip["text"] == "Hello John."
    assert detail_first_clip["translation_text"] == "Merhaba John."

    with db_conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            select text, translation_text, character_id, speaker_label, edited_by_user_id, edit_version
            from timeline_clips
            where id = %s
            """,
            (first_clip["id"],),
        )
        row = cur.fetchone()
        assert row["text"] == "Hello John."
        assert row["translation_text"] == "Merhaba John."
        assert str(row["character_id"]) == replacement_character_id
        assert row["speaker_label"] == "speaker_custom"
        assert row["edited_by_user_id"]
        assert row["edit_version"] >= 1

        cur.execute(
            "select event_type from project_events where project_id = %s",
            (project_id,),
        )
        event_types = {item["event_type"] for item in cur.fetchall()}
        for event_type in TIMELINE_EVENTS:
            assert event_type in event_types


def test_sprint8_timeline_edit_failures_do_not_break_api(client, auth_headers, valid_sample_video_file):
    project = create_project(client, auth_headers, name="Sprint 8 Failure")
    project_id = project["id"]
    upload_video(client, auth_headers, project_id, valid_sample_video_file)
    wait_for_pipeline_ready(client, auth_headers, project_id)
    client.post(f"/projects/{project_id}/characters/from-speakers", headers=auth_headers)

    timeline_response = client.get(f"/projects/{project_id}/timeline", headers=auth_headers)
    assert timeline_response.status_code == 200, timeline_response.text
    clips = timeline_response.json()["clips"]
    clip = clips[0]

    invalid_range_response = client.patch(
        f"/projects/{project_id}/timeline/clips/{clip['id']}",
        headers=auth_headers,
        json={"start_ms": clip["end_ms"], "end_ms": clip["start_ms"]},
    )
    assert invalid_range_response.status_code == 409, invalid_range_response.text

    after_failure_timeline = client.get(f"/projects/{project_id}/timeline", headers=auth_headers)
    assert after_failure_timeline.status_code == 200, after_failure_timeline.text
    after_failure_detail = client.get(f"/projects/{project_id}", headers=auth_headers)
    assert after_failure_detail.status_code == 200, after_failure_detail.text
