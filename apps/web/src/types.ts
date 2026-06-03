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
  created_at: string;
  updated_at: string;
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
  translated_text: string;
  provider: string | null;
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

export type ProjectDetail = ProjectListItem & {
  artifacts: Artifact[];
  jobs: Job[];
  events: ProjectEvent[];
  characters: Character[];
  character_assignments: CharacterAssignment[];
  transcript_segments: TranscriptSegment[];
  speaker_segments: SpeakerSegment[];
  translation_segments: TranslationSegment[];
  timeline_clips: TimelineClip[];
};

export type TimelineResponse = {
  project_id: string;
  clips: TimelineClip[];
};

export type ApiErrorResponse = {
  error: {
    code: string;
    message: string;
  };
};
