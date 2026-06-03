ALTER TYPE job_type ADD VALUE IF NOT EXISTS 'DIARIZE';

ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'DIARIZATION_STARTED';
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'SPEAKER_SEGMENT_CREATED';
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'DIARIZATION_COMPLETED';
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'TRANSCRIPT_SPEAKER_ASSIGNED';

CREATE TABLE IF NOT EXISTS speaker_segments (
  id uuid PRIMARY KEY,
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  start_ms integer NOT NULL,
  end_ms integer NOT NULL,
  speaker_label varchar(64) NOT NULL,
  confidence numeric(5,4),
  provider varchar(64),
  metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS speaker_segments_project_id_idx ON speaker_segments(project_id, start_ms);

ALTER TABLE timeline_clips
  ADD COLUMN IF NOT EXISTS speaker_label varchar(64);
