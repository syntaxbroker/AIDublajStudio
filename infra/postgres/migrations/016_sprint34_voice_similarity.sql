ALTER TABLE voice_profiles
  ADD COLUMN IF NOT EXISTS average_similarity_score numeric(5,2);
