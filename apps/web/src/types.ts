export type User = {
  id: string;
  email: string;
  full_name: string;
  role: string;
  is_active: boolean;
  created_at: string;
};

export type TokenResponse = {
  access_token: string;
  token_type: string;
};

export type ProjectListItem = {
  id: string;
  name: string;
  description: string | null;
  source_language: string | null;
  target_language: string;
  status: string;
  storage_key: string;
  created_by_user_id: string;
  created_at: string;
  updated_at: string;
};

export type Artifact = {
  id: string;
  project_id: string;
  artifact_type: string;
  status: string;
  storage_path: string;
  file_name: string;
  mime_type: string | null;
  size_bytes: number | null;
  checksum_sha256: string | null;
  duration_ms: number | null;
  created_by_job_id: string | null;
  metadata_json: Record<string, unknown>;
  parent_artifact_ids: string[];
  created_at: string;
};

export type Job = {
  id: string;
  project_id: string;
  job_type: string;
  state: string;
  queue_name: string;
  worker_name: string | null;
  gpu_device_id: number | null;
  input_json: Record<string, unknown>;
  output_json: Record<string, unknown>;
  error_json: Record<string, unknown> | null;
  queued_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  cancelled_at: string | null;
  created_at: string;
  updated_at: string;
};

export type JobLogs = {
  job_id: string;
  state: string;
  worker: string | null;
  logs: string[];
};

export type JobRetryResponse = {
  old_job_id: string;
  new_job_id: string;
  status: string;
};

export type JobClearResponse = {
  job_id: string;
  archived: boolean;
};

export type JobBulkClearResponse = {
  archived_count: number;
};

export type ProjectEvent = {
  id: string;
  event_type: string;
  entity_type: string;
  entity_id: string | null;
  payload_json: Record<string, unknown>;
  created_at: string;
};

export type TranscriptSegment = {
  id: string;
  project_id: string;
  source_artifact_id: string | null;
  segment_index: number;
  start_ms: number;
  end_ms: number;
  speaker_label: string | null;
  language_code: string | null;
  text: string;
  confidence: number | null;
  source: string;
  status: string;
  metadata_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type TranslationSegment = {
  id: string;
  project_id: string;
  transcript_segment_id: string;
  source_language: string | null;
  target_language: string;
  source_text: string | null;
  faithful_text: string | null;
  adapted_text: string | null;
  translated_text: string;
  provider: string | null;
  duration_target_ms: number | null;
  semantic_similarity_score: number | null;
  status: string;
  metadata_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type SpeakerSegment = {
  id: string;
  project_id: string;
  start_ms: number;
  end_ms: number;
  speaker_label: string;
  confidence: number | null;
  provider: string | null;
  metadata_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type Character = {
  id: string;
  project_id: string | null;
  display_name: string;
  description: string | null;
  source_type: string;
  assigned_voice_profile_id: string | null;
  assigned_voice_profile: VoiceProfile | null;
  created_at: string;
  updated_at: string;
};

export type CharacterAssignment = {
  id: string;
  project_id: string;
  character_id: string;
  speaker_label: string | null;
  transcript_segment_id: string | null;
  timeline_clip_id: string | null;
  confidence: number | null;
  assignment_source: string;
  created_at: string;
  updated_at: string;
};

export type TimelineClip = {
  id: string;
  project_id: string;
  transcript_segment_id: string | null;
  translation_segment_id: string | null;
  dub_segment_id: string | null;
  artifact_id: string | null;
  character_id: string | null;
  edited_by_user_id: string | null;
  speaker_label: string | null;
  text: string | null;
  translation_text: string | null;
  clip_type: string;
  track_index: number;
  start_ms: number;
  end_ms: number;
  lane: string;
  is_locked: boolean;
  edit_version: number;
  metadata_json: Record<string, unknown>;
  edited_at: string | null;
  created_at: string;
  updated_at: string;
};

export type DubSegment = {
  id: string;
  project_id: string;
  translation_segment_id: string | null;
  timeline_clip_id: string | null;
  character_id: string | null;
  voice_profile_id: string | null;
  text: string | null;
  audio_artifact_id: string | null;
  provider: string | null;
  status: string;
  duration_ms: number | null;
  metadata_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type VoiceProfile = {
  id: string;
  display_name: string;
  description: string | null;
  provider: string;
  voice_id: string;
  profile_type: string;
  language: string;
  gender: string | null;
  reference_audio_artifact_id: string | null;
  source_character_id: string | null;
  source_speaker_label: string | null;
  sample_duration_ms: number | null;
  quality_score: number | null;
  average_similarity_score: number | null;
  is_shared: boolean;
  status: string;
  metadata_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type ProjectDetail = ProjectListItem & {
  artifacts: Artifact[];
  jobs: Job[];
  events: ProjectEvent[];
  characters: Character[];
  character_assignments: CharacterAssignment[];
  transcript_segments: TranscriptSegment[];
  speaker_segments: SpeakerSegment[];
  translation_segments: TranslationSegment[];
  dub_segments: DubSegment[];
  timeline_clips: TimelineClip[];
};

export type TimelineResponse = {
  project_id: string;
  clips: TimelineClip[];
};

export type ProviderStatusItem = {
  capability: string;
  provider: string;
  is_mock: boolean;
};

export type ProviderStatusResponse = {
  allow_mock_providers: boolean;
  has_mock_provider: boolean;
  providers: ProviderStatusItem[];
  warning: string | null;
};

export type ProjectDurationReport = {
  project_id: string;
  max_timeline_end_ms: number | null;
  active_providers: ProviderStatusResponse;
  artifacts: {
    artifact_id: string;
    artifact_type: string;
    duration_ms: number | null;
    storage_path: string;
  }[];
};

export type ApiErrorResponse = {
  error: {
    code: string;
    message: string;
  };
};
