CREATE TYPE user_role AS ENUM ('ADMIN', 'EDITOR');
CREATE TYPE project_status AS ENUM ('ACTIVE', 'ARCHIVED', 'DELETED');
CREATE TYPE job_state AS ENUM ('PENDING', 'QUEUED', 'PROCESSING', 'COMPLETED', 'FAILED', 'CANCELLED');
CREATE TYPE job_type AS ENUM (
  'INGEST',
  'PROXY_GENERATION',
  'AUDIO_EXTRACTION',
  'WAVEFORM_GENERATION',
  'TRANSCRIBE',
  'DIARIZE',
  'TRANSLATE',
  'TTS',
  'VOICE_SAMPLE_EXTRACT',
  'AUDIO_MIX',
  'LIPSYNC',
  'RENDER'
);
CREATE TYPE artifact_type AS ENUM (
  'SOURCE_VIDEO',
  'VIDEO_METADATA',
  'THUMBNAIL',
  'PROXY_VIDEO',
  'DIALOG_AUDIO',
  'MUSIC_AUDIO',
  'EFFECTS_AUDIO',
  'AMBIENT_AUDIO',
  'TRANSCRIPT',
  'TRANSLATION',
  'TTS_AUDIO',
  'VOICE_SAMPLE_AUDIO',
  'VOICE_REFERENCE_AUDIO',
  'FINAL_DUB_AUDIO',
  'LIPSYNC_VIDEO',
  'FINAL_RENDER',
  'THUMBNAIL_IMAGE',
  'SOURCE_AUDIO',
  'WAVEFORM',
  'WAVEFORM_JSON',
  'SNAPSHOT_BUNDLE'
);
CREATE TYPE artifact_status AS ENUM ('ACTIVE', 'SUPERSEDED', 'DELETED');
CREATE TYPE event_type AS ENUM (
  'USER_LOGIN',
  'PROJECT_CREATED',
  'UPLOAD_STARTED',
  'VIDEO_UPLOADED',
  'METADATA_EXTRACTED',
  'THUMBNAIL_GENERATED',
  'PROXY_GENERATED',
  'WAVEFORM_GENERATED',
  'MEDIA_READY_FOR_TRANSCRIPTION',
  'TRANSCRIPTION_STARTED',
  'TRANSCRIPTION_SEGMENT_CREATED',
  'TRANSCRIPTION_COMPLETED',
  'TIMELINE_CLIPS_CREATED',
  'DIARIZATION_STARTED',
  'SPEAKER_SEGMENT_CREATED',
  'DIARIZATION_COMPLETED',
  'TRANSCRIPT_SPEAKER_ASSIGNED',
  'CHARACTER_CREATED',
  'CHARACTER_RENAMED',
  'CHARACTER_ASSIGNED_TO_TIMELINE',
  'TIMELINE_CLIP_UPDATED',
  'TIMELINE_CLIP_SPLIT',
  'TIMELINE_CLIPS_MERGED',
  'TRANSLATION_STARTED',
  'TRANSLATION_SEGMENT_CREATED',
  'TRANSLATION_COMPLETED',
  'TTS_STARTED',
  'DUB_SEGMENT_CREATED',
  'TTS_AUDIO_GENERATED',
  'TTS_COMPLETED',
  'AUDIO_MIX_STARTED',
  'AUDIO_SEGMENT_PLACED',
  'AUDIO_MIX_COMPLETED',
  'RENDER_COMPLETED',
  'TRANSCRIPT_GENERATED',
  'TRANSCRIPT_EDITED',
  'TRANSLATION_GENERATED',
  'TRANSLATION_MODIFIED',
  'VOICE_PROFILE_ASSIGNED',
  'VOICE_SAMPLE_EXTRACTION_STARTED',
  'VOICE_SAMPLE_AUDIO_CREATED',
  'VOICE_PROFILE_CREATED_FROM_SAMPLE',
  'VOICE_PROFILE_ASSIGNED_TO_CHARACTER',
  'TTS_GENERATED',
  'RENDER_STARTED',
  'RENDER_FINISHED',
  'JOB_STATE_CHANGED',
  'JOB_FAILED'
);
CREATE TYPE provider_capability AS ENUM (
  'ASR',
  'TRANSLATION',
  'DIARIZATION',
  'TTS',
  'LIP_SYNC',
  'SOURCE_SEPARATION',
  'EMBEDDING_FACE',
  'EMBEDDING_VOICE'
);
CREATE TYPE embedding_modality AS ENUM ('FACE', 'VOICE');
CREATE TYPE transcript_source AS ENUM ('ASR', 'MANUAL');
CREATE TYPE segment_status AS ENUM ('DRAFT', 'REVIEWED', 'APPROVED');
CREATE TYPE clip_type AS ENUM ('DIALOG', 'MUSIC', 'EFFECT', 'AMBIENT', 'MARKER');

CREATE TABLE users (
  id uuid PRIMARY KEY,
  email varchar(255) NOT NULL UNIQUE,
  password_hash text NOT NULL,
  full_name varchar(255) NOT NULL,
  role user_role NOT NULL,
  is_active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE projects (
  id uuid PRIMARY KEY,
  name varchar(255) NOT NULL,
  description text,
  source_language varchar(16),
  target_language varchar(16) NOT NULL DEFAULT 'tr',
  status project_status NOT NULL DEFAULT 'ACTIVE',
  storage_key varchar(255) NOT NULL UNIQUE,
  created_by_user_id uuid NOT NULL REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE project_members (
  id uuid PRIMARY KEY,
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role user_role NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (project_id, user_id)
);

CREATE TABLE provider_configs (
  id uuid PRIMARY KEY,
  capability provider_capability NOT NULL,
  provider_key varchar(64) NOT NULL,
  display_name varchar(128) NOT NULL,
  is_enabled boolean NOT NULL DEFAULT true,
  config_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (capability, provider_key)
);

CREATE TABLE model_registry (
  id uuid PRIMARY KEY,
  capability provider_capability NOT NULL,
  provider_config_id uuid NOT NULL REFERENCES provider_configs(id) ON DELETE CASCADE,
  model_key varchar(128) NOT NULL,
  display_name varchar(128) NOT NULL,
  version varchar(64),
  dimensions integer,
  is_default boolean NOT NULL DEFAULT false,
  metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (provider_config_id, model_key, version)
);

CREATE TABLE project_versions (
  id uuid PRIMARY KEY,
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  version_no integer NOT NULL,
  name varchar(255) NOT NULL,
  notes text,
  created_by_user_id uuid NOT NULL REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (project_id, version_no)
);

CREATE TABLE jobs (
  id uuid PRIMARY KEY,
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  project_version_id uuid REFERENCES project_versions(id) ON DELETE SET NULL,
  parent_job_id uuid REFERENCES jobs(id) ON DELETE SET NULL,
  job_type job_type NOT NULL,
  state job_state NOT NULL DEFAULT 'PENDING',
  queue_name varchar(64) NOT NULL,
  worker_name varchar(128),
  gpu_device_id integer,
  provider_config_id uuid REFERENCES provider_configs(id) ON DELETE SET NULL,
  model_registry_id uuid REFERENCES model_registry(id) ON DELETE SET NULL,
  priority integer NOT NULL DEFAULT 100,
  input_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  output_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  error_json jsonb,
  requested_by_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
  queued_at timestamptz,
  started_at timestamptz,
  completed_at timestamptz,
  cancelled_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX jobs_project_id_idx ON jobs(project_id);
CREATE INDEX jobs_state_idx ON jobs(state);
CREATE INDEX jobs_queue_name_idx ON jobs(queue_name);

CREATE TABLE job_attempts (
  id uuid PRIMARY KEY,
  job_id uuid NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  attempt_no integer NOT NULL,
  worker_name varchar(128),
  state_from job_state,
  state_to job_state NOT NULL,
  log_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  error_message text,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (job_id, attempt_no, state_to, created_at)
);

CREATE TABLE artifacts (
  id uuid PRIMARY KEY,
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  project_version_id uuid REFERENCES project_versions(id) ON DELETE SET NULL,
  created_by_job_id uuid REFERENCES jobs(id) ON DELETE SET NULL,
  artifact_type artifact_type NOT NULL,
  status artifact_status NOT NULL DEFAULT 'ACTIVE',
  storage_path text NOT NULL,
  file_name varchar(255) NOT NULL,
  mime_type varchar(128),
  size_bytes bigint,
  checksum_sha256 char(64),
  duration_ms integer,
  width integer,
  height integer,
  frame_rate numeric(8,3),
  audio_channels integer,
  sample_rate integer,
  metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX artifacts_project_id_idx ON artifacts(project_id);
CREATE INDEX artifacts_type_idx ON artifacts(artifact_type);

CREATE TABLE artifact_links (
  id uuid PRIMARY KEY,
  parent_artifact_id uuid NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
  child_artifact_id uuid NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
  relation varchar(64) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (parent_artifact_id, child_artifact_id, relation)
);

CREATE TABLE project_events (
  id uuid PRIMARY KEY,
  project_id uuid REFERENCES projects(id) ON DELETE CASCADE,
  actor_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
  related_job_id uuid REFERENCES jobs(id) ON DELETE SET NULL,
  entity_type varchar(64) NOT NULL,
  entity_id uuid,
  event_type event_type NOT NULL,
  payload_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX project_events_project_id_idx ON project_events(project_id, created_at DESC);
CREATE INDEX project_events_event_type_idx ON project_events(event_type);

CREATE TABLE character_profiles (
  id uuid PRIMARY KEY,
  project_id uuid REFERENCES projects(id) ON DELETE SET NULL,
  name varchar(255) NOT NULL,
  notes text,
  is_global boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE voice_profiles (
  id uuid PRIMARY KEY,
  display_name varchar(255) NOT NULL,
  description text,
  provider varchar(64) NOT NULL,
  voice_id varchar(255) NOT NULL,
  profile_type varchar(32) NOT NULL DEFAULT 'edge_tts',
  language varchar(16) NOT NULL DEFAULT 'tr',
  gender varchar(32),
  reference_audio_artifact_id uuid REFERENCES artifacts(id) ON DELETE SET NULL,
  source_character_id uuid,
  source_speaker_label varchar(64),
  sample_duration_ms integer,
  quality_score numeric(5,2),
  is_shared boolean NOT NULL DEFAULT true,
  status varchar(32) NOT NULL DEFAULT 'ready',
  metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (provider, voice_id)
);

CREATE TABLE embeddings (
  id uuid PRIMARY KEY,
  modality embedding_modality NOT NULL,
  owner_type varchar(64) NOT NULL,
  owner_id uuid NOT NULL,
  model_registry_id uuid NOT NULL REFERENCES model_registry(id) ON DELETE CASCADE,
  dimensions integer NOT NULL,
  embedding vector NOT NULL,
  quality_score numeric(5,2),
  source_artifact_id uuid REFERENCES artifacts(id) ON DELETE SET NULL,
  metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX embeddings_owner_idx ON embeddings(owner_type, owner_id);

CREATE TABLE transcript_segments (
  id uuid PRIMARY KEY,
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  project_version_id uuid REFERENCES project_versions(id) ON DELETE SET NULL,
  source_artifact_id uuid REFERENCES artifacts(id) ON DELETE SET NULL,
  segment_index integer NOT NULL,
  start_ms integer NOT NULL,
  end_ms integer NOT NULL,
  speaker_label varchar(64),
  language_code varchar(16),
  text text NOT NULL,
  confidence numeric(5,4),
  source transcript_source NOT NULL DEFAULT 'ASR',
  status segment_status NOT NULL DEFAULT 'DRAFT',
  metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (project_version_id, segment_index)
);

CREATE INDEX transcript_segments_project_id_idx ON transcript_segments(project_id, start_ms);

CREATE TABLE speaker_segments (
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

CREATE INDEX speaker_segments_project_id_idx ON speaker_segments(project_id, start_ms);

CREATE TABLE translation_segments (
  id uuid PRIMARY KEY,
  transcript_segment_id uuid NOT NULL REFERENCES transcript_segments(id) ON DELETE CASCADE,
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  project_version_id uuid REFERENCES project_versions(id) ON DELETE SET NULL,
  provider_config_id uuid REFERENCES provider_configs(id) ON DELETE SET NULL,
  model_registry_id uuid REFERENCES model_registry(id) ON DELETE SET NULL,
  source_language varchar(16),
  target_language varchar(16) NOT NULL DEFAULT 'tr',
  source_text text,
  translated_text text NOT NULL,
  provider varchar(64),
  duration_target_ms integer,
  status segment_status NOT NULL DEFAULT 'DRAFT',
  metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX translation_segments_project_id_idx ON translation_segments(project_id);

CREATE TABLE dub_segments (
  id uuid PRIMARY KEY,
  translation_segment_id uuid REFERENCES translation_segments(id) ON DELETE SET NULL,
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  project_version_id uuid REFERENCES project_versions(id) ON DELETE SET NULL,
  voice_profile_id uuid REFERENCES voice_profiles(id) ON DELETE SET NULL,
  tts_artifact_id uuid REFERENCES artifacts(id) ON DELETE SET NULL,
  timeline_clip_id uuid,
  character_id uuid,
  text text,
  audio_artifact_id uuid REFERENCES artifacts(id) ON DELETE SET NULL,
  provider varchar(64),
  duration_ms integer,
  similarity_score numeric(5,2),
  duration_match_score numeric(5,2),
  emotion_match_score numeric(5,2),
  overall_score numeric(5,2),
  regen_count integer NOT NULL DEFAULT 0,
  status segment_status NOT NULL DEFAULT 'DRAFT',
  metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX dub_segments_project_id_idx ON dub_segments(project_id);

CREATE TABLE timeline_clips (
  id uuid PRIMARY KEY,
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  project_version_id uuid REFERENCES project_versions(id) ON DELETE SET NULL,
  transcript_segment_id uuid REFERENCES transcript_segments(id) ON DELETE SET NULL,
  translation_segment_id uuid REFERENCES translation_segments(id) ON DELETE SET NULL,
  dub_segment_id uuid REFERENCES dub_segments(id) ON DELETE SET NULL,
  artifact_id uuid REFERENCES artifacts(id) ON DELETE SET NULL,
  character_id uuid,
  edited_by_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
  speaker_label varchar(64),
  text text,
  translation_text text,
  clip_type clip_type NOT NULL DEFAULT 'DIALOG',
  track_index integer NOT NULL DEFAULT 0,
  start_ms integer NOT NULL,
  end_ms integer NOT NULL,
  lane varchar(32) NOT NULL DEFAULT 'dialog',
  is_locked boolean NOT NULL DEFAULT false,
  edit_version integer NOT NULL DEFAULT 0,
  metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  edited_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT timeline_clips_range_check CHECK (start_ms < end_ms)
);

CREATE INDEX timeline_clips_project_id_idx ON timeline_clips(project_id, start_ms);

CREATE TABLE characters (
  id uuid PRIMARY KEY,
  project_id uuid REFERENCES projects(id) ON DELETE CASCADE,
  display_name varchar(255) NOT NULL,
  description text,
  source_type varchar(32) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX characters_project_id_idx ON characters(project_id);

CREATE TABLE character_assignments (
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

CREATE INDEX character_assignments_project_id_idx ON character_assignments(project_id);
CREATE UNIQUE INDEX character_assignments_speaker_unique_idx
  ON character_assignments(project_id, character_id, speaker_label)
  WHERE speaker_label IS NOT NULL AND transcript_segment_id IS NULL AND timeline_clip_id IS NULL;

CREATE TABLE character_voice_assignments (
  id uuid PRIMARY KEY,
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  character_id uuid NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
  voice_profile_id uuid NOT NULL REFERENCES voice_profiles(id) ON DELETE CASCADE,
  assignment_source varchar(32) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (project_id, character_id)
);

CREATE INDEX character_voice_assignments_project_id_idx ON character_voice_assignments(project_id);

ALTER TABLE voice_profiles
  ADD CONSTRAINT voice_profiles_source_character_id_fkey
  FOREIGN KEY (source_character_id) REFERENCES characters(id) ON DELETE SET NULL;

CREATE TABLE project_settings (
  id uuid PRIMARY KEY,
  project_id uuid NOT NULL UNIQUE REFERENCES projects(id) ON DELETE CASCADE,
  default_asr_provider_config_id uuid REFERENCES provider_configs(id) ON DELETE SET NULL,
  default_translation_provider_config_id uuid REFERENCES provider_configs(id) ON DELETE SET NULL,
  default_tts_provider_config_id uuid REFERENCES provider_configs(id) ON DELETE SET NULL,
  default_lipsync_provider_config_id uuid REFERENCES provider_configs(id) ON DELETE SET NULL,
  source_resolution varchar(32),
  proxy_resolution varchar(32) NOT NULL DEFAULT '1280x720',
  target_resolution varchar(32) NOT NULL DEFAULT '1920x1080',
  metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
