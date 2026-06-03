ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'TTS_STARTED';
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'DUB_SEGMENT_CREATED';
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'TTS_AUDIO_GENERATED';
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'TTS_COMPLETED';

ALTER TABLE dub_segments
  ALTER COLUMN translation_segment_id DROP NOT NULL;

ALTER TABLE dub_segments
  ADD COLUMN IF NOT EXISTS timeline_clip_id uuid,
  ADD COLUMN IF NOT EXISTS character_id uuid,
  ADD COLUMN IF NOT EXISTS text text,
  ADD COLUMN IF NOT EXISTS audio_artifact_id uuid REFERENCES artifacts(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS provider varchar(64),
  ADD COLUMN IF NOT EXISTS duration_ms integer;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'dub_segments_timeline_clip_id_fkey'
  ) THEN
    ALTER TABLE dub_segments
      ADD CONSTRAINT dub_segments_timeline_clip_id_fkey
      FOREIGN KEY (timeline_clip_id) REFERENCES timeline_clips(id) ON DELETE SET NULL;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'dub_segments_character_id_fkey'
  ) THEN
    ALTER TABLE dub_segments
      ADD CONSTRAINT dub_segments_character_id_fkey
      FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE SET NULL;
  END IF;
END $$;
