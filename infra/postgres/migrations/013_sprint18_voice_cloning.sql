ALTER TYPE job_type ADD VALUE IF NOT EXISTS 'VOICE_SAMPLE_EXTRACT';
ALTER TYPE artifact_type ADD VALUE IF NOT EXISTS 'VOICE_SAMPLE_AUDIO';
ALTER TYPE artifact_type ADD VALUE IF NOT EXISTS 'VOICE_REFERENCE_AUDIO';
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'VOICE_SAMPLE_EXTRACTION_STARTED';
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'VOICE_SAMPLE_AUDIO_CREATED';
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'VOICE_PROFILE_CREATED_FROM_SAMPLE';
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'VOICE_PROFILE_ASSIGNED_TO_CHARACTER';

ALTER TABLE voice_profiles
  ADD COLUMN IF NOT EXISTS profile_type varchar(32) NOT NULL DEFAULT 'edge_tts',
  ADD COLUMN IF NOT EXISTS reference_audio_artifact_id uuid REFERENCES artifacts(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS source_character_id uuid,
  ADD COLUMN IF NOT EXISTS source_speaker_label varchar(64),
  ADD COLUMN IF NOT EXISTS sample_duration_ms integer,
  ADD COLUMN IF NOT EXISTS status varchar(32) NOT NULL DEFAULT 'ready';

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.table_constraints
    WHERE constraint_name = 'voice_profiles_source_character_id_fkey'
      AND table_name = 'voice_profiles'
  ) THEN
    ALTER TABLE voice_profiles
      ADD CONSTRAINT voice_profiles_source_character_id_fkey
      FOREIGN KEY (source_character_id) REFERENCES characters(id) ON DELETE SET NULL;
  END IF;
END $$;
