ALTER TABLE translation_segments
  ADD COLUMN IF NOT EXISTS faithful_text text,
  ADD COLUMN IF NOT EXISTS adapted_text text,
  ADD COLUMN IF NOT EXISTS semantic_similarity_score numeric(5,2);

UPDATE translation_segments
SET faithful_text = COALESCE(faithful_text, translated_text),
    adapted_text = COALESCE(adapted_text, translated_text),
    semantic_similarity_score = COALESCE(semantic_similarity_score, 1.00)
WHERE translated_text IS NOT NULL;
