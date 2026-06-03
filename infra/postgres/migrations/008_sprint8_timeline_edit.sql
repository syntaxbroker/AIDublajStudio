ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'TIMELINE_CLIP_UPDATED';
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'TIMELINE_CLIP_SPLIT';
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'TIMELINE_CLIPS_MERGED';

ALTER TABLE timeline_clips
  ADD COLUMN IF NOT EXISTS edited_by_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS text text,
  ADD COLUMN IF NOT EXISTS translation_text text,
  ADD COLUMN IF NOT EXISTS edit_version integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS edited_at timestamptz;

ALTER TABLE timeline_clips
  DROP CONSTRAINT IF EXISTS timeline_clips_range_check;

ALTER TABLE timeline_clips
  ADD CONSTRAINT timeline_clips_range_check CHECK (start_ms < end_ms);
