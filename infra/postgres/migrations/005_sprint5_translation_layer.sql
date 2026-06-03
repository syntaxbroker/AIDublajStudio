ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'TRANSLATION_STARTED';
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'TRANSLATION_SEGMENT_CREATED';
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'TRANSLATION_COMPLETED';

ALTER TABLE translation_segments
  ADD COLUMN IF NOT EXISTS source_language varchar(16),
  ADD COLUMN IF NOT EXISTS source_text text,
  ADD COLUMN IF NOT EXISTS translated_text text,
  ADD COLUMN IF NOT EXISTS provider varchar(64);

UPDATE translation_segments
SET translated_text = text
WHERE translated_text IS NULL;

ALTER TABLE translation_segments
  ALTER COLUMN translated_text SET NOT NULL;
