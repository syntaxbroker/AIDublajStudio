ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'CHARACTER_CREATED';
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'CHARACTER_RENAMED';
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'CHARACTER_ASSIGNED_TO_TIMELINE';

ALTER TABLE timeline_clips
  ADD COLUMN IF NOT EXISTS character_id uuid;

CREATE TABLE IF NOT EXISTS characters (
  id uuid PRIMARY KEY,
  project_id uuid REFERENCES projects(id) ON DELETE CASCADE,
  display_name varchar(255) NOT NULL,
  description text,
  source_type varchar(32) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS characters_project_id_idx ON characters(project_id);

CREATE TABLE IF NOT EXISTS character_assignments (
  id uuid PRIMARY KEY,
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  character_id uuid NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
  speaker_label varchar(64),
  transcript_segment_id uuid REFERENCES transcript_segments(id) ON DELETE CASCADE,
  timeline_clip_id uuid REFERENCES timeline_clips(id) ON DELETE CASCADE,
  confidence numeric(5,4),
  assignment_source varchar(32) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS character_assignments_project_id_idx ON character_assignments(project_id);
CREATE UNIQUE INDEX IF NOT EXISTS character_assignments_speaker_unique_idx
  ON character_assignments(project_id, character_id, speaker_label)
  WHERE speaker_label IS NOT NULL AND transcript_segment_id IS NULL AND timeline_clip_id IS NULL;
