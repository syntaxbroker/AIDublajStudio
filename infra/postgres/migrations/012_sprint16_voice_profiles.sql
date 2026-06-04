ALTER TABLE voice_profiles
  DROP COLUMN IF EXISTS character_profile_id,
  DROP COLUMN IF EXISTS source_artifact_id,
  DROP COLUMN IF EXISTS duration_seconds,
  DROP COLUMN IF EXISTS is_library_eligible,
  DROP COLUMN IF EXISTS notes,
  ADD COLUMN IF NOT EXISTS description text,
  ADD COLUMN IF NOT EXISTS provider varchar(64) NOT NULL DEFAULT 'edge_tts',
  ADD COLUMN IF NOT EXISTS voice_id varchar(255) NOT NULL DEFAULT 'tr-TR-AhmetNeural',
  ADD COLUMN IF NOT EXISTS language varchar(16) NOT NULL DEFAULT 'tr',
  ADD COLUMN IF NOT EXISTS gender varchar(32),
  ADD COLUMN IF NOT EXISTS is_shared boolean NOT NULL DEFAULT true,
  ADD COLUMN IF NOT EXISTS metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE voice_profiles
  ADD CONSTRAINT voice_profiles_provider_voice_id_unique UNIQUE (provider, voice_id);

CREATE TABLE IF NOT EXISTS character_voice_assignments (
  id uuid PRIMARY KEY,
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  character_id uuid NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
  voice_profile_id uuid NOT NULL REFERENCES voice_profiles(id) ON DELETE CASCADE,
  assignment_source varchar(32) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (project_id, character_id)
);

CREATE INDEX IF NOT EXISTS character_voice_assignments_project_id_idx
  ON character_voice_assignments(project_id);
